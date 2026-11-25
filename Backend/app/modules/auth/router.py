"""AUT-01..04 · Sesión con WorkOS AuthKit, patrón BFF.

1. El FE navega (no fetch) a GET /auth/login?return_to=/ruta.
2. El backend redirige al Hosted UI de AuthKit; el usuario inicia sesión allí.
3. AuthKit vuelve a GET /auth/callback; el backend crea la cookie de sesión y
   redirige al FE en return_to.
4. El FE llama a la API con la cookie (fetch con credentials) y usa GET /auth/me.
   Un 401 trae el motivo en `code`: NO_AUTENTICADO, SESION_EXPIRADA (8 h),
   SESION_INACTIVA (15 min sin uso) o SESION_REVOCADA (bloqueo, desactivación o
   cambio de rol).
5. Logout: POST /auth/logout y el FE navega a la logoutUrl que recibe.

Una sola sesión abierta por usuario: con otra abierta en otro dispositivo, el login
vuelve a /login?error=SESION_ABIERTA y la abierta sigue.

AUT-05..09 · Usuarios internos (router_usuarios, /usuarios): solo ADMIN.
"""

from datetime import datetime
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo

from fastapi import (
    APIRouter,
    Cookie,
    Depends,
    HTTPException,
    Path,
    Query,
    Request,
    Response,
)
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import Connection

from app.core.api.errors import (
    RESPUESTAS_ERROR,
    ProblemDetailsRoute,
    problema,
    solo_parametros,
)
from app.core.api.middleware import ip_cliente
from app.core.config.settings import get_settings
from app.core.database.db import cooperativa, seguridad
from app.core.security.auth import (
    COOKIE_SESION,
    Rol,
    Usuario,
    UsuarioActual,
    UsuarioAuditoria,
    borrar_cookie_sesion,
    codigo_agencia,
    guardar_cookie_sesion,
    motivo_rechazo,
    no_autenticado,
    normalizar_roles,
    require_auth,
    require_roles,
    verificar_origen,
)
from app.core.security.origen import resolver_origen_front
from app.modules.aprobaciones.contratos import SolicitudAceptada
from app.modules.auth import agencias as multiagencia
from app.modules.auth import agencias_repository as agencias_repo
from app.modules.auth import repository, service
from app.modules.auth.agencias_schemas import (
    AsignacionesEntrada,
    AsignacionesUsuario,
    CambioAgencia,
    ContextoAgencias,
    HistorialAgencias,
    SeleccionAgencia,
    TrasladoUsuario,
)
from app.modules.auth.schemas import (
    EstadoUsuario,
    LogoutResponse,
    PageUsuario,
    RolUpdate,
    UsuarioCreate,
    UsuarioDetalle,
    UsuarioSesion,
    UsuarioUpdate,
)
from app.modules.organizacion import exportacion

COOKIE_STATE = "__Host-oauth_state"
_DURACION_STATE = 10 * 60  # tiempo para completar el login en el Hosted UI
_MAX_USER_AGENT = 512
_MAX_PARAMETRO = 2048

CookieSesion = Annotated[str | None, Cookie(alias=COOKIE_SESION, max_length=8192)]
ParametroCallback = Annotated[str | None, Query(max_length=_MAX_PARAMETRO)]


def _sin_cache(response: Response) -> None:
    """Datos de sesión no deben quedar en caché de navegadores ni proxies."""
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"


# Sin require_auth a nivel de router: login y callback son públicos. Las demás
# rutas validan la sesión con UsuarioActual o leen la cookie directamente.
router = APIRouter(
    prefix="/auth",
    route_class=ProblemDetailsRoute,
    responses=RESPUESTAS_ERROR,
    tags=["auth"],
    dependencies=[Depends(_sin_cache)],
)


def _ip(request: Request) -> str | None:
    # La IP confiable la resuelve ip_cliente (solo del Worker con el secreto)
    return ip_cliente(request.scope)


def _user_agent(request: Request) -> str | None:
    agente = request.headers.get("user-agent")
    return agente[:_MAX_USER_AGENT] if agente else None


def _redireccion(url: str) -> RedirectResponse:
    respuesta = RedirectResponse(url, status_code=302)
    _sin_cache(respuesta)
    return respuesta


# AUT-01. Público. El FE navega aquí con window.location, no con fetch
@router.get("/login", response_class=RedirectResponse, status_code=302)
def login(
    request: Request,
    return_to: Annotated[str | None, Query(max_length=512)] = None,
) -> RedirectResponse:
    """Redirige al Hosted UI de AuthKit. `return_to` es la ruta del FE a la que se
    vuelve después; si no es una ruta interna se usa "/".
    """
    url, valor_state = service.iniciar_login(return_to, resolver_origen_front(request))
    respuesta = _redireccion(url)
    # Lax: tiene que viajar en la navegación de vuelta desde WorkOS
    respuesta.set_cookie(
        COOKIE_STATE,
        valor_state,
        max_age=_DURACION_STATE,
        path="/",
        secure=True,
        httponly=True,
        samesite="lax",
    )
    return respuesta


# AUT-01. Público. Es la WORKOS_REDIRECT_URI (o la de la preview): aquí vuelve AuthKit
@router.get("/callback", response_class=RedirectResponse, status_code=302)
def callback(
    request: Request,
    code: ParametroCallback = None,
    state: ParametroCallback = None,
    error: ParametroCallback = None,
    cookie_state: Annotated[
        str | None, Cookie(alias=COOKIE_STATE, max_length=1024)
    ] = None,
    cookie_sesion: CookieSesion = None,
) -> RedirectResponse:
    """Crea la cookie de sesión y vuelve al FE, o a /login?error=CODIGO si falla.
    SESION_ABIERTA: el usuario ya tiene una sesión abierta en otro dispositivo.
    """
    destino, sellada = service.completar_login(
        code,
        state,
        error,
        cookie_state,
        _ip(request),
        _user_agent(request),
        resolver_origen_front(request),
        cookie_sesion,
    )
    respuesta = _redireccion(destino)
    respuesta.delete_cookie(
        COOKIE_STATE, path="/", secure=True, httponly=True, samesite="lax"
    )
    if sellada:
        guardar_cookie_sesion(respuesta, sellada)
    return respuesta


# AUT-02. Requiere cookie de sesión. Opcional: /me y las demás rutas ya renuevan solas
@router.post("/refresh", status_code=204, dependencies=[Depends(verificar_origen)])
def refresh(response: Response, sellada: CookieSesion = None) -> None:
    """Renueva el access token de la sesión y reescribe la cookie."""
    sesion = service.refrescar(sellada)
    if sesion is None or not sesion.sellada_nueva:
        raise no_autenticado(borrar_cookie=True, motivo=motivo_rechazo(sellada))
    guardar_cookie_sesion(response, sesion.sellada_nueva)


# AUT-03. Idempotente: sin sesión también responde 200
@router.post(
    "/logout", response_model=LogoutResponse, dependencies=[Depends(verificar_origen)]
)
def logout(request: Request, response: Response, sellada: CookieSesion = None) -> Any:
    """Borra la cookie y devuelve la URL que cierra la sesión en AuthKit."""
    url = service.cerrar_sesion(sellada, _ip(request), resolver_origen_front(request))
    borrar_cookie_sesion(response)
    return LogoutResponse(logout_url=url)


# AUT-04. Roles: AUTH. require_auth: una sesión viva de un usuario que luego se
# bloquea o desactiva responde 403 USUARIO_NO_REGISTRADO
@router.get("/me", response_model=UsuarioSesion)
def me(usuario: Annotated[Usuario, Depends(require_auth)]) -> Any:
    """Usuario de la sesión, sus roles, permisos y agencia vigente. 403 si no está
    registrado o no está Activo.
    """
    return service.perfil(usuario)


# --- AUT-05..09 · Usuarios internos (C-05). Roles: ADMIN -------------------------

ConexionSeguridad = Annotated[Connection, Depends(seguridad)]
ConexionCooperativa = Annotated[Connection, Depends(cooperativa)]
Admin = Annotated[Usuario, Depends(require_roles("ADMIN"))]
EditorUsuarios = Annotated[Usuario, Depends(require_roles("ADMIN"))]
IdUsuario = Annotated[int, Path(alias="idUsuario", ge=1)]

router_usuarios = APIRouter(
    prefix="/usuarios",
    route_class=ProblemDetailsRoute,
    responses={**RESPUESTAS_ERROR, 503: {"description": "WorkOS no disponible"}},
    tags=["usuarios"],
    dependencies=[Depends(require_auth), Depends(_sin_cache)],
)


directorio_router = APIRouter(
    prefix="/seguridad",
    tags=["seguridad"],
    route_class=ProblemDetailsRoute,
    responses=RESPUESTAS_ERROR,
    dependencies=[Depends(require_auth), Depends(_sin_cache)],
)


def autorizar_listado_usuarios(
    request: Request, usuario: UsuarioActual, formato: Literal["csv"] | None = None
) -> Usuario:
    directorio = request.url.path.endswith("/directorio-usuarios")
    if formato == "csv" or (
        directorio and exportacion.PERMISO_EXPORTAR in usuario.permisos
    ):
        exportacion.autorizar(usuario)
    else:
        roles = ("ADMIN", "AUDITOR") if directorio else ("ADMIN",)
        require_roles(*roles)(usuario, request)
    return usuario


@directorio_router.get(
    "/directorio-usuarios",
    response_model=PageUsuario,
    operation_id="OrganizacionDirectorioUsuarios",
    responses=exportacion.RESPUESTA_CSV,
)
@router_usuarios.get(
    "",
    response_model=PageUsuario,
    operation_id="AUT05",
    responses=exportacion.RESPUESTA_CSV,
)
def listar_usuarios(
    request: Request,
    usuario: Annotated[Usuario, Depends(autorizar_listado_usuarios)],
    _parametros: Annotated[
        None,
        Depends(
            solo_parametros(
                "q",
                "estado",
                "idAgencia",
                "idUsuario",
                "nombre",
                "rol",
                "vinculado",
                "page",
                "pageSize",
                "sort",
                "formato",
            )
        ),
    ],
    conn: ConexionSeguridad,
    q: Annotated[str | None, Query(max_length=100)] = None,
    filtro_id_usuario: Annotated[
        int | None, Query(alias="idUsuario", ge=1, le=2147483647)
    ] = None,
    nombre: Annotated[str | None, Query(max_length=100)] = None,
    estado: EstadoUsuario | None = None,
    id_agencia: Annotated[
        str | None, Query(alias="idAgencia", pattern=r"^\d{3}$")
    ] = None,
    rol: Rol | None = None,
    vinculado: bool | None = None,
    page: Annotated[int, Query(ge=1, le=1_000_000)] = 1,
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=100)] = 20,
    sort: Annotated[str | None, Query(max_length=40)] = None,
    formato: Literal["csv"] | None = None,
) -> PageUsuario | Response:
    """Usuarios internos con búsqueda (username, nombres, apellidos, email), filtros y
    paginación. Orden: idUsuario, username, nombres, apellidos, email, roles,
    idAgencia, estado o fechaCreacion,
    con ,asc o ,desc (por defecto fechaCreacion,desc).
    """
    if formato == "csv":
        filas, _ = repository.listar_usuarios(
            conn,
            q=q.strip() if q else None,
            estado=estado,
            agencia_id=int(id_agencia) if id_agencia else None,
            rol=rol,
            vinculado=vinculado,
            orden=service.orden_listado(sort),
            page=page,
            page_size=page_size,
            id_usuario=filtro_id_usuario,
            nombre=nombre.strip() if nombre else None,
        )
        return exportacion.responder_csv(
            usuario,
            ip_cliente(request.scope),
            "usuarios",
            "Organizacion.Usuarios",
            (
                "idUsuario",
                "usuario",
                "nombres",
                "apellidos",
                "documento",
                "estado",
                "roles",
                "idAgencia",
            ),
            (
                (
                    f["UsuarioID"],
                    f["NombreUsuario"],
                    f["Nombres"],
                    f["Apellidos"],
                    exportacion.enmascarar_documento(f["Cedula"]),
                    f["Estado"],
                    ",".join(
                        normalizar_roles((f["RolesWorkOS"] or "").split(","), None)
                    ),
                    codigo_agencia(f["AgenciaID"]),
                )
                for f in filas
            ),
        )
    return service.listar_usuarios(
        conn,
        q=q,
        estado=estado,
        id_agencia=id_agencia,
        rol=rol,
        vinculado=vinculado,
        page=page,
        page_size=page_size,
        sort=sort,
        id_usuario=filtro_id_usuario,
        nombre=nombre,
    )


@router_usuarios.post(
    "", response_model=UsuarioDetalle, status_code=201, operation_id="AUT06"
)
def crear_usuario(
    request: Request,
    admin: EditorUsuarios,
    datos: UsuarioCreate,
    conn: ConexionSeguridad,
    conn_coop: ConexionCooperativa,
) -> UsuarioDetalle:
    """Crea el usuario y lo invita a EnquoCoop con su rol. La contraseña la define el
    usuario al aceptar la invitación; queda vinculado en su primer login.
    """
    return service.crear_usuario(
        conn, conn_coop, datos, admin, ip_cliente(request.scope)
    )


@router_usuarios.get(
    "/{idUsuario}", response_model=UsuarioDetalle, operation_id="AUT07"
)
def obtener_usuario(
    _admin: Admin,
    _parametros: Annotated[None, Depends(solo_parametros())],
    id_usuario: IdUsuario,
    conn: ConexionSeguridad,
) -> UsuarioDetalle:
    """Detalle para precargar la edición. estadoInvitacion solo si no está vinculado."""
    return service.obtener_usuario(conn, id_usuario)


@router_usuarios.patch(
    "/{idUsuario}", response_model=UsuarioDetalle, operation_id="AUT08"
)
def actualizar_usuario(
    request: Request,
    admin: EditorUsuarios,
    id_admin: UsuarioAuditoria,
    id_usuario: IdUsuario,
    cambios: UsuarioUpdate,
    conn: ConexionSeguridad,
    conn_coop: ConexionCooperativa,
) -> UsuarioDetalle:
    """Edita nombres, apellidos, email, estado (motivo obligatorio al bloquear) e
    idAgencia. Bloquear o desactivar corta las sesiones del usuario en WorkOS.
    """
    return service.actualizar_usuario(
        conn,
        conn_coop,
        id_usuario,
        cambios,
        admin,
        id_admin,
        ip_cliente(request.scope),
    )


@router_usuarios.put(
    "/{idUsuario}/agencia", response_model=UsuarioDetalle, operation_id="E104Agencia"
)
def trasladar_usuario(
    request: Request,
    admin: EditorUsuarios,
    id_admin: UsuarioAuditoria,
    id_usuario: IdUsuario,
    datos: TrasladoUsuario,
    conn: ConexionSeguridad,
    conn_coop: ConexionCooperativa,
) -> UsuarioDetalle:
    return service.actualizar_usuario(
        conn,
        conn_coop,
        id_usuario,
        UsuarioUpdate(id_agencia=datos.id_agencia),
        admin,
        id_admin,
        ip_cliente(request.scope),
    )


@router_usuarios.put(
    "/{idUsuario}/roles",
    response_model=UsuarioDetalle,
    operation_id="AUT09",
    responses={202: {"model": SolicitudAceptada}},
)
def cambiar_rol(
    request: Request,
    admin: EditorUsuarios,
    id_admin: UsuarioAuditoria,
    id_usuario: IdUsuario,
    datos: RolUpdate,
    conn: ConexionSeguridad,
    conn_coop: ConexionCooperativa,
) -> UsuarioDetalle | JSONResponse:
    """Reemplaza el conjunto de roles y cierra las sesiones del usuario."""
    try:
        return service.cambiar_rol(
            conn,
            conn_coop,
            id_usuario,
            datos,
            admin,
            id_admin,
            ip_cliente(request.scope),
        )
    except HTTPException as error:
        detalle: Any = error.detail
        if not (
            isinstance(detalle, dict)
            and detalle.get("code") == "APROBACION_REQUERIDA"
            and get_settings().e104_politica_roles_activa
            and get_settings().e104_permiso_aprobar_roles.strip()
        ):
            raise
    from app.modules.aprobaciones import router as aprobaciones
    from app.modules.aprobaciones.registro import Objetivo
    from app.modules.auth.aprobacion_roles import CODIGO, TIPO

    actor = aprobaciones.actual(admin)
    if not actor.global_admin or actor.id_interno == id_usuario:
        raise problema(
            403, "SIN_PERMISO", "El solicitante carece de autorización vigente."
        )
    solicitud = aprobaciones.servicio().solicitar(
        actor,
        CODIGO,
        Objetivo(TIPO, str(id_usuario), None),
        datos.model_dump(mode="json", by_alias=True),
        datetime.now(ZoneInfo("America/Guayaquil")).date(),
        aprobaciones.contexto(request, admin),
    )
    return JSONResponse(
        status_code=202,
        content=SolicitudAceptada(id_solicitud=solicitud).model_dump(by_alias=True),
    )


# #450: rutas de asignaciones reutilizan los routers BFF existentes.


def _editor_asignaciones(admin: Admin, _: EditorUsuarios) -> Usuario:
    return admin


EditorAsignaciones = Annotated[Usuario, Depends(_editor_asignaciones)]


@router_usuarios.get(
    "/{idUsuario}/agencias",
    response_model=AsignacionesUsuario,
    operation_id="AUTAgenciasUsuario",
)
def agencias_usuario(
    _admin: Admin,
    id_usuario: IdUsuario,
    conn: ConexionSeguridad,
    coop: ConexionCooperativa,
) -> AsignacionesUsuario:
    return multiagencia.consultar(conn, coop, id_usuario)


@router_usuarios.put(
    "/{idUsuario}/agencias",
    response_model=AsignacionesUsuario,
    operation_id="AUTGuardarAgencias",
)
def guardar_agencias(
    request: Request,
    actor: EditorAsignaciones,
    id_usuario: IdUsuario,
    datos: AsignacionesEntrada,
    conn: ConexionSeguridad,
    coop: ConexionCooperativa,
) -> AsignacionesUsuario:
    return multiagencia.guardar(
        conn, coop, id_usuario, datos, actor, ip_cliente(request.scope)
    )


@router_usuarios.get(
    "/{idUsuario}/historial",
    response_model=HistorialAgencias,
    operation_id="E104HistorialAgencias",
)
@router_usuarios.get(
    "/{idUsuario}/agencias/historial",
    response_model=HistorialAgencias,
    operation_id="AUTHistorialAgencias",
)
def historial_agencias(
    _admin: Admin,
    id_usuario: IdUsuario,
    conn: ConexionSeguridad,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=100)] = 20,
) -> HistorialAgencias:
    service._cargar(conn, id_usuario)
    rows, total = agencias_repo.historial(conn, id_usuario, page, page_size)
    return HistorialAgencias(
        items=[CambioAgencia.model_validate(r) for r in rows],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get(
    "/agencias", response_model=ContextoAgencias, operation_id="AUTAgenciasSesion"
)
def agencias_sesion(
    actor: Annotated[Usuario, Depends(require_auth)],
) -> ContextoAgencias:
    return multiagencia.contexto_usuario(actor)


@router.post(
    "/agencia-activa",
    response_model=ContextoAgencias,
    operation_id="AUTSeleccionarAgencia",
)
def seleccionar_agencia(
    request: Request,
    actor: Annotated[Usuario, Depends(require_auth)],
    datos: SeleccionAgencia,
    conn: ConexionSeguridad,
    coop: ConexionCooperativa,
) -> ContextoAgencias:
    return multiagencia.seleccionar(
        conn, coop, actor, datos.id_agencia, ip_cliente(request.scope)
    )
