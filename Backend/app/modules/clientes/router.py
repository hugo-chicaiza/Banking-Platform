from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import Connection

from app.core.api.errors import RESPUESTAS_ERROR, ProblemDetailsRoute
from app.core.api.middleware import ip_cliente
from app.core.database.db import cooperativa
from app.core.security.auth import (
    Usuario,
    UsuarioAuditoria,
    require_auth,
    require_roles,
)
from app.modules.clientes import service
from app.modules.clientes.schemas import (
    Cliente,
    ClienteCreate,
    ClienteEstadoUpdate,
    ClientePerfil,
    ClienteUpdate,
    Direccion,
    DireccionNueva,
    DireccionUpdate,
    EstadoCliente,
    PageCliente,
    PageClienteHistorial,
    Riesgo,
    RiesgoCreate,
    RiesgoRegistrado,
    TipoCliente,
    TipoDocumento,
    ValidacionIdentificacion,
)

router = APIRouter(
    tags=["clientes"],
    dependencies=[Depends(require_auth)],
)
_gestion_router = APIRouter(route_class=ProblemDetailsRoute, responses=RESPUESTAS_ERROR)

Db = Annotated[Connection, Depends(cooperativa)]

# Roles de cada tarea (GitHubProject_Files): 403 SIN_PERMISO si no tiene ninguno
_ASESOR_ADMIN = [Depends(require_roles("ASESOR", "ADMIN"))]

_consultas_router = APIRouter(route_class=ProblemDetailsRoute)
_ROLES_CONSULTA = ["ASESOR", "CAJERO", "SUPERVISOR", "ADMIN"]


@_consultas_router.get(
    "",
    operation_id="CLI03",
    response_model=PageCliente,
    responses=RESPUESTAS_ERROR,
    dependencies=[Depends(require_roles(*_ROLES_CONSULTA))],
    openapi_extra={"x-roles": _ROLES_CONSULTA},
)
def listar_clientes(
    conn: Db,
    q: str | None = None,
    identificacion: str | None = None,
    tipo_cliente: Annotated[TipoCliente | None, Query(alias="tipoCliente")] = None,
    estado: EstadoCliente | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=100)] = 20,
    sort: str | None = None,
) -> PageCliente:
    """Busca clientes por filtros combinados, con paginación (CLI-03 / C-03)."""
    return service.listar_clientes(
        conn,
        q=q,
        identificacion=identificacion,
        tipo_cliente=tipo_cliente,
        estado=estado,
        page=page,
        page_size=page_size,
        sort=sort,
    )


@_consultas_router.get(
    "/{idCliente}",
    operation_id="CLI04",
    response_model=Cliente,
    responses=RESPUESTAS_ERROR,
    dependencies=[Depends(require_roles(*_ROLES_CONSULTA))],
    openapi_extra={"x-roles": _ROLES_CONSULTA},
)
def obtener_cliente(idCliente: int, conn: Db) -> Cliente:
    """Detalle del cliente con sus direcciones activas (CLI-04 / C-03)."""
    return service.obtener_cliente(conn, idCliente)


@_consultas_router.get(
    "/{idCliente}/perfil",
    operation_id="CLI08",
    response_model=ClientePerfil,
    responses=RESPUESTAS_ERROR,
    dependencies=[Depends(require_roles("ASESOR", "SUPERVISOR", "ADMIN"))],
    openapi_extra={"x-roles": ["ASESOR", "SUPERVISOR", "ADMIN"]},
)
def obtener_perfil_cliente(idCliente: int, conn: Db) -> ClientePerfil:
    """Datos generales, riesgo vigente y productos financieros (CLI-08 / C-06)."""
    return service.obtener_perfil_cliente(conn, idCliente)


# ---------------------------------------------------------------------------
# GET /api/v1/clientes/validar-identificacion
# ---------------------------------------------------------------------------
# Roles: ASESOR, ADMIN


@_gestion_router.get(
    "/validar-identificacion",
    operation_id="CLI01",
    response_model=ValidacionIdentificacion,
    dependencies=_ASESOR_ADMIN,
)
def validar_identificacion(
    tipo_documento: Annotated[
        TipoDocumento,
        Query(
            description="Tipo de documento: C (Cédula), R (RUC), P (Pasaporte)",
            alias="tipoDocumento",
        ),
    ],
    identificacion: Annotated[
        str,
        Query(
            description="Número de documento de identificación",
            min_length=1,
            max_length=20,
        ),
    ],
    conn: Db,
) -> Any:
    """Valida formato del documento (Módulo 10 para Cédula/RUC) y si ya existe (CLI-01 / C-02)."""
    return service.validar_identificacion(conn, tipo_documento, identificacion)


# ---------------------------------------------------------------------------
# POST /api/v1/clientes
# ---------------------------------------------------------------------------
# Roles: ASESOR, ADMIN


@_gestion_router.post(
    "",
    operation_id="CLI02",
    response_model=Cliente,
    status_code=201,
    dependencies=_ASESOR_ADMIN,
)
def registrar_cliente(
    payload: ClienteCreate,
    request: Request,
    creado_por: UsuarioAuditoria,
    conn: Db,
) -> Any:
    """Registra un cliente (Natural o Jurídico) con su dirección principal (CLI-02 / C-01).

    `creado_por` es el usuario de la sesión, vinculado por Organizacion.Usuarios.KeyUsuario.
    """
    # Obtener IP del cliente para auditoría en ClientesHis
    direccion_ip = _ip_cliente(request)

    return service.registrar_cliente(conn, payload, creado_por, direccion_ip)


# ---------------------------------------------------------------------------
# GET /api/v1/clientes/{idCliente}/direcciones
# ---------------------------------------------------------------------------
# Roles: ASESOR, ADMIN


@_gestion_router.get(
    "/{idCliente}/direcciones",
    operation_id="CLI09",
    response_model=list[Direccion],
    dependencies=_ASESOR_ADMIN,
)
def listar_direcciones(
    idCliente: int,
    conn: Db,
) -> Any:
    """Retorna las direcciones activas e inactivas del cliente (CLI-09 / C-07)."""
    return service.listar_direcciones(conn, idCliente)


# ---------------------------------------------------------------------------
# POST /api/v1/clientes/{idCliente}/direcciones
# ---------------------------------------------------------------------------
# Roles: ASESOR, ADMIN


@_gestion_router.post(
    "/{idCliente}/direcciones",
    operation_id="CLI10",
    response_model=Direccion,
    status_code=201,
    dependencies=_ASESOR_ADMIN,
)
def agregar_direccion(
    idCliente: int,
    payload: DireccionNueva,
    request: Request,
    modificado_por: UsuarioAuditoria,
    conn: Db,
) -> Any:
    """Agrega una nueva dirección al cliente (CLI-10 / C-07)."""
    direccion_ip = _ip_cliente(request)
    return service.agregar_direccion(
        conn, idCliente, payload, modificado_por, direccion_ip
    )


# ---------------------------------------------------------------------------
# PATCH /api/v1/clientes/{idCliente}/direcciones/{idDireccion}
# ---------------------------------------------------------------------------
# Roles: ASESOR, ADMIN


@_gestion_router.patch(
    "/{idCliente}/direcciones/{idDireccion}",
    operation_id="CLI11",
    response_model=Direccion,
    dependencies=_ASESOR_ADMIN,
)
def editar_direccion(
    idCliente: int,
    idDireccion: int,
    payload: DireccionUpdate,
    request: Request,
    modificado_por: UsuarioAuditoria,
    conn: Db,
) -> Any:
    """Edita una dirección o la promueve a principal."""
    direccion_ip = _ip_cliente(request)
    return service.editar_direccion(
        conn, idCliente, idDireccion, payload, modificado_por, direccion_ip
    )


# ---------------------------------------------------------------------------
# DELETE /api/v1/clientes/{idCliente}/direcciones/{idDireccion}
# ---------------------------------------------------------------------------
# Roles: ASESOR, ADMIN


@_gestion_router.delete(
    "/{idCliente}/direcciones/{idDireccion}",
    operation_id="CLI12",
    status_code=204,
    dependencies=_ASESOR_ADMIN,
)
def eliminar_direccion(
    idCliente: int,
    idDireccion: int,
    request: Request,
    modificado_por: UsuarioAuditoria,
    conn: Db,
) -> Response:
    """Baja lógica de una dirección (CLI-12 / C-07)."""
    service.eliminar_direccion(
        conn, idCliente, idDireccion, modificado_por, _ip_cliente(request)
    )
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Helpers internos del router
# ---------------------------------------------------------------------------


def _ip_cliente(request: Request) -> str:
    """Obtiene la IP del cliente desde los headers o la conexión."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "127.0.0.1"


_riesgo_router = APIRouter(route_class=ProblemDetailsRoute)


@_riesgo_router.post(
    "/{idCliente}/evaluaciones-riesgo",
    operation_id="CLI13",
    response_model=RiesgoRegistrado,
    status_code=201,
    responses=RESPUESTAS_ERROR,
    dependencies=[Depends(require_roles("ASESOR", "SUPERVISOR", "ADMIN"))],
    openapi_extra={"x-roles": ["ASESOR", "SUPERVISOR", "ADMIN"]},
)
def registrar_evaluacion_riesgo(
    idCliente: int,
    payload: RiesgoCreate,
    request: Request,
    evaluador: UsuarioAuditoria,
    conn: Db,
) -> RiesgoRegistrado:
    """Registra riesgo y devuelve el estado posterior al trigger (CLI-13 / C-08)."""
    return service.registrar_evaluacion_riesgo(
        conn, idCliente, payload, evaluador, _ip_cliente(request)
    )


@_riesgo_router.get(
    "/{idCliente}/evaluaciones-riesgo",
    operation_id="CLI14",
    response_model=list[Riesgo],
    responses=RESPUESTAS_ERROR,
    dependencies=[Depends(require_roles("ASESOR", "SUPERVISOR", "AUDITOR", "ADMIN"))],
    openapi_extra={"x-roles": ["ASESOR", "SUPERVISOR", "AUDITOR", "ADMIN"]},
)
def listar_evaluaciones_riesgo(idCliente: int, conn: Db) -> list[Riesgo]:
    """Historial de evaluaciones por fecha e identificador descendentes (CLI-14)."""
    return service.listar_evaluaciones_riesgo(conn, idCliente)


_edicion_router = APIRouter(
    route_class=ProblemDetailsRoute,
    responses={
        **RESPUESTAS_ERROR,
        503: {**RESPUESTAS_ERROR[500], "description": "Service Unavailable"},
    },
)
EditorCliente = Annotated[Usuario, Depends(require_roles("ASESOR", "ADMIN"))]
GestorEstado = Annotated[
    Usuario, Depends(require_roles("ASESOR", "SUPERVISOR", "ADMIN"))
]
LectorHistorial = Annotated[
    Usuario, Depends(require_roles("SUPERVISOR", "AUDITOR", "ADMIN"))
]


@_edicion_router.patch(
    "/{idCliente}",
    operation_id="CLI05",
    response_model=Cliente,
    openapi_extra={"x-roles": ["ASESOR", "ADMIN"]},
)
def editar_cliente(
    idCliente: int,
    payload: ClienteUpdate,
    request: Request,
    usuario: EditorCliente,
    modificado_por: UsuarioAuditoria,
    conn: Db,
) -> Cliente:
    """Edita datos y audita cada cambio con la identidad vinculada en el servidor."""
    return service.editar_cliente(
        conn, idCliente, payload, modificado_por, ip_cliente(request.scope)
    )


@_edicion_router.patch(
    "/{idCliente}/estado",
    operation_id="CLI06",
    response_model=Cliente,
    openapi_extra={"x-roles": ["ASESOR", "SUPERVISOR", "ADMIN"]},
)
def cambiar_estado_cliente(
    idCliente: int,
    payload: ClienteEstadoUpdate,
    request: Request,
    usuario: GestorEstado,
    modificado_por: UsuarioAuditoria,
    conn: Db,
) -> Cliente:
    """Transición explícita, con comprobación de productos para la baja."""
    return service.cambiar_estado_cliente(
        conn,
        idCliente,
        payload,
        modificado_por,
        ip_cliente(request.scope),
        usuario.roles,
    )


@_edicion_router.get(
    "/{idCliente}/historial",
    operation_id="CLI07",
    response_model=PageClienteHistorial,
    openapi_extra={"x-roles": ["SUPERVISOR", "AUDITOR", "ADMIN"]},
)
def listar_historial_cliente(
    idCliente: int,
    usuario: LectorHistorial,
    conn: Db,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=100)] = 20,
    sort: str | None = None,
) -> PageClienteHistorial:
    """Historial inmutable; exige una sesión válida de WorkOS y el rol indicado."""
    return service.listar_historial_cliente(
        conn, idCliente, page=page, page_size=page_size, sort=sort
    )


router.include_router(_gestion_router, prefix="/clientes")
router.include_router(_edicion_router, prefix="/clientes")
router.include_router(_riesgo_router, prefix="/clientes")
router.include_router(_consultas_router, prefix="/clientes")
