"""Organización · Mantenimiento de agencias y entidad.

Sin DELETE: la baja es lógica por Estado. Solo ADMIN (decisión del responsable,
2026-11-12). La identidad es la sesión de WorkOS; el UsuarioID de auditoría es el mismo
vínculo que usan todos los módulos (require_auth / UsuarioAuditoria).
"""

from datetime import datetime
from typing import Annotated, Any, Literal, TypeVar
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Path, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import Connection

from app.core.api.errors import RESPUESTAS_ERROR, ProblemDetailsRoute, solo_parametros
from app.core.api.middleware import ip_cliente, obtener_trace_id
from app.core.database.db import cooperativa
from app.core.security.auth import (
    Usuario,
    UsuarioActual,
    UsuarioAuditoria,
    require_auth,
    require_roles,
)
from app.core.security.operador import auditar
from app.modules.aprobaciones import router as aprobaciones
from app.modules.aprobaciones.contratos import SolicitudAceptada
from app.modules.aprobaciones.registro import Objetivo
from app.modules.organizacion import exportacion, service
from app.modules.organizacion.aprobacion import CODIGO_BAJA, TIPO_OBJETIVO
from app.modules.organizacion.schemas import (
    Agencia,
    AgenciaCreate,
    AgenciaEstado,
    AgenciaEstadoUpdate,
    AgenciaUpdate,
    Entidad,
    EntidadCreate,
    EntidadUpdate,
    EstadoAgencia,
    PresentacionInstitucion,
)
from app.modules.seguridad import service as seguridad_service
from app.modules.seguridad.schemas import RolVista

_ROLES = ["ADMIN"]
router_publico = APIRouter(
    prefix="/institucion", tags=["Institución"], route_class=ProblemDetailsRoute
)


@router_publico.get(
    "",
    response_model=PresentacionInstitucion,
    operation_id="InstitucionConsultar",
    responses={503: RESPUESTAS_ERROR[503]},
)
def consultar_institucion(response: Response) -> PresentacionInstitucion:
    """Solo presentación pública para login/encabezados. No escribe ni usa WorkOS."""
    response.headers["Cache-Control"] = "no-store"
    return service.obtener_presentacion()


_ACEPTADA: dict[int | str, dict[str, Any]] = {
    202: {"model": SolicitudAceptada, "description": "Solicitud pendiente"}
}


def _solicitar_baja(
    request: Request, usuario: Usuario, id_agencia: str
) -> service.SolicitarBaja:
    def solicitar(motivo: str | None) -> SolicitudAceptada:
        actor = aprobaciones.actual(usuario)
        aprobaciones.alcance_operativo(actor, usuario, id_agencia)
        id_solicitud = aprobaciones.servicio().solicitar(
            actor,
            CODIGO_BAJA,
            Objetivo(TIPO_OBJETIVO, id_agencia, id_agencia),
            {"motivo": motivo},
            datetime.now(ZoneInfo("America/Guayaquil")).date(),
            aprobaciones.contexto(request, usuario),
        )
        return SolicitudAceptada(id_solicitud=id_solicitud)

    return solicitar


router = APIRouter(
    route_class=ProblemDetailsRoute,
    responses=RESPUESTAS_ERROR,
    dependencies=[Depends(require_auth)],
)

Db = Annotated[Connection, Depends(cooperativa)]
IdAgenciaPath = Annotated[str, Path(pattern=r"^[0-9A-Z]{3}$")]


def autorizar_listado_agencias(
    request: Request, usuario: UsuarioActual, formato: Literal["csv"] | None = None
) -> Usuario:
    if formato == "csv":
        exportacion.autorizar(usuario)
    else:
        roles = (
            ("ADMIN", "AUDITOR")
            if request.url.path.endswith("/directorio-agencias")
            else _ROLES
        )
        require_roles(*roles)(usuario, request)
    return usuario


@router.get(
    "/organizacion/agencias",
    tags=["organizacion"],
    operation_id="AgenciaListar",
    response_model=list[Agencia],
    responses=exportacion.RESPUESTA_CSV,
    dependencies=[Depends(solo_parametros("estado", "formato", "q"))],
    openapi_extra={"x-roles": _ROLES},
)
@router.get(
    "/seguridad/directorio-agencias",
    operation_id="OrganizacionDirectorioAgencias",
    response_model=list[Agencia],
    responses=exportacion.RESPUESTA_CSV,
    dependencies=[Depends(solo_parametros("estado", "formato", "q"))],
)
def listar_agencias(
    request: Request,
    usuario: Annotated[Usuario, Depends(autorizar_listado_agencias)],
    conn: Db,
    estado: EstadoAgencia | None = None,
    formato: Literal["csv"] | None = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
) -> list[Agencia] | Response:
    agencias = service.listar_agencias(conn, estado)
    if q:
        busqueda = q.strip().upper()
        agencias = [
            a
            for a in agencias
            if busqueda in a.codigo.upper() or busqueda in a.id_agencia
        ]
    if formato is None:
        return agencias
    return exportacion.responder_csv(
        usuario,
        ip_cliente(request.scope),
        "agencias",
        "Organizacion.Agencia",
        ("idAgencia", "codigo", "tipoAgencia", "estado"),
        ((a.id_agencia, a.codigo, a.tipo_agencia, a.estado) for a in agencias),
    )


@router.get(
    "/seguridad/matriz-roles",
    tags=["organizacion"],
    operation_id="OrganizacionMatrizRoles",
    response_model=list[RolVista],
    responses=exportacion.RESPUESTA_CSV,
    dependencies=[Depends(solo_parametros("formato"))],
)
def matriz_roles(
    request: Request,
    usuario: UsuarioActual,
    formato: Literal["csv"] | None = None,
) -> list[RolVista] | Response:
    if formato is None:
        require_roles("ADMIN", "AUDITOR")(usuario, request)
        return seguridad_service.listar_roles()
    exportacion.autorizar(usuario)
    roles = seguridad_service.listar_roles()
    return exportacion.responder_csv(
        usuario,
        ip_cliente(request.scope),
        "matriz-roles",
        "Seguridad.Grupos",
        ("rol", "nombre", "permiso"),
        (
            (rol.rol, rol.nombre, permiso)
            for rol in roles
            for permiso in rol.permisos or [""]
        ),
    )


@router.post(
    "/organizacion/agencias",
    tags=["organizacion"],
    operation_id="OrganizacionAgenciaCrear",
    response_model=Agencia,
    status_code=201,
    dependencies=[
        Depends(require_roles(*_ROLES)),
        Depends(solo_parametros()),
    ],
    openapi_extra={"x-roles": _ROLES},
)
@router.post(
    "/agencias",
    tags=["organizacion"],
    operation_id="ORG01",
    response_model=Agencia,
    status_code=201,
    dependencies=[
        Depends(require_roles(*_ROLES)),
        Depends(solo_parametros()),
    ],
    openapi_extra={"x-roles": _ROLES},
)
def crear_agencia(
    payload: AgenciaCreate,
    request: Request,
    usuario: Annotated[Usuario, Depends(require_auth)],
    creado_por: UsuarioAuditoria,
    conn: Db,
) -> Agencia:
    """Crea una agencia en Estado 'I'. SQL genera idAgencia automáticamente."""
    return service.crear_agencia(
        conn,
        payload,
        creado_por,
        ip_cliente(request.scope),
        obtener_trace_id(request.scope),
        usuario,
    )


@router.get(
    "/organizacion/agencias/{id_agencia}",
    tags=["organizacion"],
    operation_id="OrganizacionAgenciaObtener",
    response_model=Agencia,
    dependencies=[Depends(require_roles(*_ROLES)), Depends(solo_parametros())],
    openapi_extra={"x-roles": _ROLES},
)
@router.get(
    "/agencias/{id_agencia}",
    tags=["organizacion"],
    operation_id="AgenciaObtener",
    response_model=Agencia,
    dependencies=[Depends(solo_parametros()), Depends(require_roles(*_ROLES))],
    openapi_extra={"x-roles": _ROLES},
)
def obtener_agencia(id_agencia: IdAgenciaPath, conn: Db) -> Agencia:
    return service.obtener_agencia(conn, id_agencia)


@router.patch(
    "/organizacion/agencias/{id_agencia}",
    responses=_ACEPTADA,
    tags=["organizacion"],
    operation_id="OrganizacionAgenciaEditar",
    response_model=Agencia,
    dependencies=[
        Depends(require_roles(*_ROLES)),
        Depends(solo_parametros()),
    ],
    openapi_extra={"x-roles": _ROLES},
)
@router.patch(
    "/agencias/{id_agencia}",
    responses=_ACEPTADA,
    tags=["organizacion"],
    operation_id="ORG02",
    response_model=Agencia,
    dependencies=[
        Depends(require_roles(*_ROLES)),
        Depends(solo_parametros()),
    ],
    openapi_extra={"x-roles": _ROLES},
)
def actualizar_agencia(
    id_agencia: IdAgenciaPath,
    payload: AgenciaUpdate,
    request: Request,
    response: Response,
    usuario: Annotated[Usuario, Depends(require_auth)],
    modificado_por: UsuarioAuditoria,
    conn: Db,
) -> Agencia | Response:
    """Actualiza datos y permite reactivar la agencia. La baja requiere una segunda persona."""
    resultado = service.actualizar_agencia(
        conn,
        id_agencia,
        payload,
        modificado_por,
        ip_cliente(request.scope),
        obtener_trace_id(request.scope),
        usuario,
        _solicitar_baja(request, usuario, id_agencia),
    )
    return _respuesta_estado(resultado, response)


# Endpoint heredado del compañero: conservar ruta, operación y auditoría.
T = TypeVar("T", Agencia, AgenciaEstado)


def _respuesta_estado(
    resultado: T | SolicitudAceptada, response: Response
) -> T | Response:
    if isinstance(resultado, SolicitudAceptada):
        return JSONResponse(
            resultado.model_dump(mode="json", by_alias=True),
            status_code=202,
            headers=dict(response.headers),
        )
    return resultado


def _sin_cache(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"


@router.patch(
    "/organizacion/agencias/{id_agencia}/estado",
    response_model=AgenciaEstado,
    responses=_ACEPTADA,
    tags=["organizacion"],
    operation_id="OrganizacionAgenciaCambiarEstado",
    openapi_extra={"x-roles": _ROLES},
    dependencies=[
        Depends(require_roles(*_ROLES)),
        Depends(solo_parametros()),
        Depends(_sin_cache),
    ],
)
@router.patch(
    "/agencias/{id_agencia}/estado",
    responses=_ACEPTADA,
    response_model=AgenciaEstado,
    tags=["organizacion"],
    operation_id="AgenciaCambiarEstado",
    openapi_extra={"x-roles": _ROLES},
    dependencies=[
        Depends(require_roles(*_ROLES)),
        Depends(solo_parametros()),
        Depends(_sin_cache),
    ],
)
def cambiar_estado(
    id_agencia: Annotated[str, Path(min_length=3, max_length=3)],
    datos: AgenciaEstadoUpdate,
    conn: Db,
    request: Request,
    response: Response,
    usuario: Annotated[Usuario, Depends(require_auth)],
) -> AgenciaEstado | Response:
    if datos.estado == "I":
        resultado = service.solicitar_estado_inactivo(
            conn,
            id_agencia,
            datos.motivo,
            _solicitar_baja(request, usuario, id_agencia),
        )
        return _respuesta_estado(resultado, response)
    resultado, _ = service.cambiar_estado(
        conn,
        id_agencia,
        datos.estado,
        actor=usuario,
        ip=ip_cliente(request.scope),
        trace_id=obtener_trace_id(request.scope),
        motivo=datos.motivo,
    )
    return resultado


@router.get(
    "/organizacion/entidad",
    tags=["Organización"],
    response_model=Entidad,
    operation_id="EntidadObtener",
    summary="Obtener la entidad",
    openapi_extra={"x-roles": ["ASESOR", "ADMIN"]},
    dependencies=[
        Depends(_sin_cache),
        Depends(require_roles("ASESOR", "ADMIN")),
        Depends(solo_parametros()),
    ],
)
def obtener_entidad(conn: Db) -> Entidad:
    """Devuelve la entidad con IdEntidad = 1, incluso si está inactiva.

    Requiere sesión y rol ASESOR o ADMIN. Si falta el registro, responde
    404 ENTIDAD_NO_ENCONTRADA.
    """
    return service.obtener_entidad(conn)


@router.post(
    "/organizacion/entidad",
    tags=["Organización"],
    response_model=Entidad,
    status_code=201,
    operation_id="EntidadCrear",
    summary="Crear la entidad",
    openapi_extra={"x-roles": ["ADMIN"]},
    dependencies=[Depends(solo_parametros()), Depends(_sin_cache)],
)
def crear_entidad(
    datos: EntidadCreate,
    conn: Db,
    request: Request,
    modificado_por: UsuarioAuditoria,
    usuario: Annotated[Usuario, Depends(require_roles("ADMIN"))],
) -> Entidad:
    """Crea el registro inicial con IdEntidad = 1. Requiere ADMIN.

    Devuelve 201 con la entidad persistida. Si el registro ya existe, responde
    409 ENTIDAD_YA_EXISTE. Los campos idEntidad, fechaRegistro y modificadoPor
    son administrados por el backend. SQL Server asigna FechaRegistro y
    ModificadoPor se obtiene de la sesión. El contrato exige ruc, razonSocial,
    fechaConstitucion, representanteLegal e identificacionRepresentante.
    TipoOrganizacion toma 'Cooperativa de Ahorro y Credito' y Estado toma 'A'
    cuando se omiten. Los campos anulables omitidos se guardan como NULL.
    La creación se audita después del commit.
    """
    resultado = service.crear_entidad(conn, datos, modificado_por)
    with auditar(
        "CREAR_ENTIDAD",
        "Organizacion.Entidad",
        usuario,
        ip_cliente(request.scope),
        "alta",
        str(resultado.id_entidad),
    ):
        pass
    return resultado


@router.patch(
    "/organizacion/entidad",
    tags=["Organización"],
    response_model=Entidad,
    operation_id="EntidadEditar",
    summary="Editar parcialmente la entidad",
    openapi_extra={"x-roles": ["ADMIN"]},
    dependencies=[Depends(solo_parametros()), Depends(_sin_cache)],
)
def editar_entidad(
    datos: EntidadUpdate,
    conn: Db,
    request: Request,
    modificado_por: UsuarioAuditoria,
    usuario: Annotated[Usuario, Depends(require_roles("ADMIN"))],
) -> Entidad:
    """Actualiza IdEntidad = 1 y devuelve todos sus datos persistidos.

    Requiere ADMIN. Envíe al menos un campo editable. Omitir un campo conserva
    su valor y null vacía los campos anulables. Los campos idEntidad,
    fechaRegistro y modificadoPor son administrados por el backend.
    ModificadoPor se obtiene de la sesión. Un cuerpo inválido responde
    400 DATOS_INVALIDOS. Una entidad inexistente responde
    404 ENTIDAD_NO_ENCONTRADA. Repetir los valores actuales devuelve 200
    sin otra escritura de auditoría. Los cambios efectivos se auditan
    después del commit mediante el mecanismo best-effort existente.
    """
    resultado, campos = service.editar_entidad(conn, datos, modificado_por)
    if campos:
        with auditar(
            "EDITAR_ENTIDAD",
            "Organizacion.Entidad",
            usuario,
            ip_cliente(request.scope),
            "campos=" + ",".join(campos),
            str(resultado.id_entidad),
        ):
            pass
    return resultado
