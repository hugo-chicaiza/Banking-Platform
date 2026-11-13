"""AUT-01..04 · Sesión con WorkOS AuthKit, patrón BFF.

1. El FE navega (no fetch) a GET /auth/login?return_to=/ruta.
2. El backend redirige al Hosted UI de AuthKit; el usuario inicia sesión allí.
3. AuthKit vuelve a GET /auth/callback; el backend crea la cookie de sesión y
   redirige al FE en return_to.
4. El FE llama a la API con la cookie (fetch con credentials) y usa GET /auth/me.
5. Logout: POST /auth/logout y el FE navega a la logoutUrl que recibe.

AUT-05..09 · Usuarios internos (router_usuarios, /usuarios): solo ADMIN.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Cookie, Depends, Path, Query, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import Connection

from app.core.api.errors import RESPUESTAS_ERROR, ProblemDetailsRoute, solo_parametros
from app.core.api.middleware import ip_cliente
from app.core.database.db import cooperativa, seguridad
from app.core.security.auth import (
    COOKIE_SESION,
    Rol,
    Usuario,
    UsuarioAuditoria,
    borrar_cookie_sesion,
    guardar_cookie_sesion,
    no_autenticado,
    require_auth,
    require_roles,
    verificar_origen,
)
from app.core.security.origen import resolver_origen_front
from app.modules.auth import service
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
    # X-Forwarded-For no se lee porque el cliente puede falsificarlo
    return request.client.host if request.client else None


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
) -> RedirectResponse:
    """Crea la cookie de sesión y vuelve al FE, o a /login?error=CODIGO si falla."""
    destino, sellada = service.completar_login(
        code,
        state,
        error,
        cookie_state,
        _ip(request),
        _user_agent(request),
        resolver_origen_front(request),
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
        raise no_autenticado(borrar_cookie=True)
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
IdUsuario = Annotated[int, Path(alias="idUsuario", ge=1)]

router_usuarios = APIRouter(
    prefix="/usuarios",
    route_class=ProblemDetailsRoute,
    responses={**RESPUESTAS_ERROR, 503: {"description": "WorkOS no disponible"}},
    tags=["usuarios"],
    dependencies=[Depends(require_auth), Depends(_sin_cache)],
)


@router_usuarios.get("", response_model=PageUsuario, operation_id="AUT05")
def listar_usuarios(
    _admin: Admin,
    _parametros: Annotated[
        None,
        Depends(
            solo_parametros(
                "q",
                "estado",
                "idAgencia",
                "rol",
                "vinculado",
                "page",
                "pageSize",
                "sort",
            )
        ),
    ],
    conn: ConexionSeguridad,
    q: Annotated[str | None, Query(max_length=100)] = None,
    estado: EstadoUsuario | None = None,
    id_agencia: Annotated[
        str | None, Query(alias="idAgencia", pattern=r"^\d{3}$")
    ] = None,
    rol: Rol | None = None,
    vinculado: bool | None = None,
    page: Annotated[int, Query(ge=1, le=1_000_000)] = 1,
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=100)] = 20,
    sort: Annotated[str | None, Query(max_length=40)] = None,
) -> PageUsuario:
    """Usuarios internos con búsqueda (username, nombres, apellidos, email), filtros y
    paginación. Orden: username, nombres, apellidos, email, estado o fechaCreacion
    con ,asc o ,desc (por defecto fechaCreacion,desc).
    """
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
    )


@router_usuarios.post(
    "", response_model=UsuarioDetalle, status_code=201, operation_id="AUT06"
)
def crear_usuario(
    request: Request,
    admin: Admin,
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
    admin: Admin,
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
    "/{idUsuario}/roles", response_model=UsuarioDetalle, operation_id="AUT09"
)
def cambiar_rol(
    request: Request,
    admin: Admin,
    id_usuario: IdUsuario,
    datos: RolUpdate,
    conn: ConexionSeguridad,
    conn_coop: ConexionCooperativa,
) -> UsuarioDetalle:
    """Reemplaza el rol del usuario (uno). Regla: no se quita el último ADMIN."""
    return service.cambiar_rol(
        conn, conn_coop, id_usuario, datos, admin, ip_cliente(request.scope)
    )
