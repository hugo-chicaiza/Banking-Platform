from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import Connection

from app.core.api.errors import RESPUESTAS_ERROR, ProblemDetailsRoute
from app.core.database.db import cooperativa
from app.core.security.auth import require_auth
from app.modules.clientes import service
from app.modules.clientes.schemas import (
    Cliente,
    ClienteCreate,
    Direccion,
    DireccionNueva,
    DireccionUpdate,
    Riesgo,
    RiesgoCreate,
    RiesgoRegistrado,
    TipoDocumento,
    ValidacionIdentificacion,
)

router = APIRouter(
    prefix="/clientes",
    tags=["clientes"],
    dependencies=[Depends(require_auth)],
)

Db = Annotated[Connection, Depends(cooperativa)]

# ---------------------------------------------------------------------------
# GET /api/v1/clientes/validar-identificacion
# ---------------------------------------------------------------------------
# Roles: ASESOR, ADMIN
# TODO(F-03): restringir por rol cuando require_auth valide el JWT.


@router.get("/validar-identificacion", response_model=ValidacionIdentificacion)
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
# TODO(F-03): restringir por rol y extraer creado_por del token JWT.


@router.post("", response_model=Cliente, status_code=201)
def registrar_cliente(
    payload: ClienteCreate,
    request: Request,
    conn: Db,
) -> Any:
    """Registra un cliente (Natural o Jurídico) con su dirección principal (CLI-02 / C-01).

    **Nota de autenticación (F-03):** `require_auth()` todavía no valida el
    JWT de WorkOS. El `creado_por` se fija temporalmente a 1; cuando F-03
    esté implementado se leerá del sub/id del token.
    """
    creado_por = 1

    # Obtener IP del cliente para auditoría en ClientesHis
    direccion_ip = _ip_cliente(request)

    return service.registrar_cliente(conn, payload, creado_por, direccion_ip)


# ---------------------------------------------------------------------------
# GET /api/v1/clientes/{idCliente}/direcciones
# ---------------------------------------------------------------------------
# Roles: ASESOR, ADMIN


@router.get(
    "/{idCliente}/direcciones",
    response_model=list[Direccion],
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


@router.post(
    "/{idCliente}/direcciones",
    response_model=Direccion,
    status_code=201,
)
def agregar_direccion(
    idCliente: int,
    payload: DireccionNueva,
    request: Request,
    conn: Db,
) -> Any:
    """Agrega una nueva dirección al cliente (CLI-10 / C-07)."""
    modificado_por = 1
    direccion_ip = _ip_cliente(request)
    return service.agregar_direccion(
        conn, idCliente, payload, modificado_por, direccion_ip
    )


# ---------------------------------------------------------------------------
# PATCH /api/v1/clientes/{idCliente}/direcciones/{idDireccion}
# ---------------------------------------------------------------------------
# Roles: ASESOR, ADMIN


@router.patch(
    "/{idCliente}/direcciones/{idDireccion}",
    response_model=Direccion,
)
def editar_direccion(
    idCliente: int,
    idDireccion: int,
    payload: DireccionUpdate,
    request: Request,
    conn: Db,
) -> Any:
    """Edita una dirección o la promueve a principal (CLI-11 / C-07)."""
    modificado_por = 1
    direccion_ip = _ip_cliente(request)
    return service.editar_direccion(
        conn, idCliente, idDireccion, payload, modificado_por, direccion_ip
    )


# ---------------------------------------------------------------------------
# DELETE /api/v1/clientes/{idCliente}/direcciones/{idDireccion}
# ---------------------------------------------------------------------------
# Roles: ASESOR, ADMIN


@router.delete(
    "/{idCliente}/direcciones/{idDireccion}",
    status_code=204,
)
def eliminar_direccion(
    idCliente: int,
    idDireccion: int,
    conn: Db,
) -> Response:
    """Baja lógica de una dirección (CLI-12 / C-07)."""
    service.eliminar_direccion(conn, idCliente, idDireccion)
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


# TODO(F-03): aplicar los roles declarados y extraer evaluador del JWT validado.
_riesgo_router = APIRouter(route_class=ProblemDetailsRoute)


@_riesgo_router.post(
    "/{idCliente}/evaluaciones-riesgo",
    operation_id="CLI13",
    response_model=RiesgoRegistrado,
    status_code=201,
    responses=RESPUESTAS_ERROR,
    openapi_extra={"x-roles": ["ASESOR", "SUPERVISOR", "ADMIN"]},
)
def registrar_evaluacion_riesgo(
    idCliente: int, payload: RiesgoCreate, request: Request, conn: Db
) -> RiesgoRegistrado:
    """Registra riesgo y devuelve el estado posterior al trigger (CLI-13 / C-08)."""
    evaluador = 1
    return service.registrar_evaluacion_riesgo(
        conn, idCliente, payload, evaluador, _ip_cliente(request)
    )


@_riesgo_router.get(
    "/{idCliente}/evaluaciones-riesgo",
    operation_id="CLI14",
    response_model=list[Riesgo],
    responses=RESPUESTAS_ERROR,
    openapi_extra={"x-roles": ["ASESOR", "SUPERVISOR", "AUDITOR", "ADMIN"]},
)
def listar_evaluaciones_riesgo(idCliente: int, conn: Db) -> list[Riesgo]:
    """Historial de evaluaciones por fecha e identificador descendentes (CLI-14)."""
    return service.listar_evaluaciones_riesgo(conn, idCliente)


router.include_router(_riesgo_router)
