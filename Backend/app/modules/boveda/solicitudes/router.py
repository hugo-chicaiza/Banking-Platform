"""Rutas del flujo de autorización independiente de BOV04."""

from typing import Annotated

from fastapi import APIRouter, Body, Depends, Header, Path, Query, Request
from sqlalchemy import Connection

from app.core.api.errors import RESPUESTAS_ERROR, ProblemDetailsRoute, solo_parametros
from app.core.api.middleware import ip_cliente
from app.core.database.db import cooperativa
from app.core.security.auth import Usuario, require_roles
from app.core.security.operador import IdInterno
from app.modules.boveda.schemas import INT32_MAX, INT64_MAX, MovimientoBoveda
from app.modules.boveda.solicitudes import service
from app.modules.boveda.solicitudes.schemas import (
    ConfirmacionRequest,
    EstadoSolicitud,
    PageSolicitudMovimiento,
    ResolucionRequest,
    SolicitudMovimiento,
    SolicitudMovimientoRequest,
)

router = APIRouter(route_class=ProblemDetailsRoute, responses=RESPUESTAS_ERROR)
Conexion = Annotated[Connection, Depends(cooperativa)]
Operador = Annotated[Usuario, Depends(require_roles("SUPERVISOR", "ADMIN"))]
Lector = Annotated[
    Usuario, Depends(require_roles("SUPERVISOR", "CONTADOR", "AUDITOR", "ADMIN"))
]
IdSolicitud = Annotated[int, Path(alias="idSolicitudMovimiento", gt=0, le=INT64_MAX)]
SinParametros = Annotated[None, Depends(solo_parametros())]


@router.post(
    "/bovedas/{idBoveda}/solicitudes-movimiento",
    status_code=201,
    response_model=SolicitudMovimiento,
    operation_id="BOV04Solicitud",
)
def crear(
    id_boveda: Annotated[int, Path(alias="idBoveda", gt=0, le=INT32_MAX)],
    datos: SolicitudMovimientoRequest,
    request: Request,
    usuario: Operador,
    id_interno: IdInterno,
    conn: Conexion,
    _: SinParametros,
    clave: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            min_length=1,
            max_length=64,
            pattern=r"^[A-Za-z0-9_-]+$",
        ),
    ] = None,
) -> SolicitudMovimiento:
    return service.crear(
        conn, usuario, id_interno, id_boveda, datos, ip_cliente(request.scope), clave
    )


@router.get(
    "/solicitudes-movimiento",
    response_model=PageSolicitudMovimiento,
    operation_id="BOV04Solicitudes",
)
def listar(
    usuario: Lector,
    conn: Conexion,
    _: Annotated[
        None, Depends(solo_parametros("idAgencia", "estado", "page", "pageSize"))
    ],
    id_agencia: Annotated[
        str | None, Query(alias="idAgencia", pattern=r"^\d{3}$")
    ] = None,
    estado: EstadoSolicitud | None = None,
    page: Annotated[int, Query(ge=1, le=INT32_MAX)] = 1,
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=100)] = 20,
) -> PageSolicitudMovimiento:
    return service.listar(conn, usuario, id_agencia, estado, page, page_size)


@router.get(
    "/solicitudes-movimiento/{idSolicitudMovimiento}",
    response_model=SolicitudMovimiento,
    operation_id="BOV04SolicitudDetalle",
)
def obtener(
    id_solicitud: IdSolicitud, usuario: Lector, conn: Conexion, _: SinParametros
) -> SolicitudMovimiento:
    return service.obtener(conn, usuario, id_solicitud)


@router.post(
    "/solicitudes-movimiento/{idSolicitudMovimiento}/aprobacion",
    status_code=201,
    response_model=list[MovimientoBoveda],
    operation_id="BOV04SolicitudAprobacion",
)
def aprobar(
    id_solicitud: IdSolicitud,
    request: Request,
    usuario: Operador,
    id_interno: IdInterno,
    conn: Conexion,
    _: SinParametros,
    confirmacion: Annotated[ConfirmacionRequest | None, Body()] = None,
) -> list[MovimientoBoveda]:
    return service.aprobar(
        conn, usuario, id_interno, id_solicitud, ip_cliente(request.scope)
    )


@router.post(
    "/solicitudes-movimiento/{idSolicitudMovimiento}/rechazo",
    response_model=SolicitudMovimiento,
    operation_id="BOV04SolicitudRechazo",
)
def rechazar(
    id_solicitud: IdSolicitud,
    datos: ResolucionRequest,
    request: Request,
    usuario: Operador,
    id_interno: IdInterno,
    conn: Conexion,
    _: SinParametros,
) -> SolicitudMovimiento:
    return service.resolver_sin_ejecucion(
        conn,
        usuario,
        id_interno,
        id_solicitud,
        "RECHAZADA",
        datos.motivo,
        ip_cliente(request.scope),
    )


@router.post(
    "/solicitudes-movimiento/{idSolicitudMovimiento}/cancelacion",
    response_model=SolicitudMovimiento,
    operation_id="BOV04SolicitudCancelacion",
)
def cancelar(
    id_solicitud: IdSolicitud,
    datos: ResolucionRequest,
    request: Request,
    usuario: Operador,
    id_interno: IdInterno,
    conn: Conexion,
    _: SinParametros,
) -> SolicitudMovimiento:
    return service.resolver_sin_ejecucion(
        conn,
        usuario,
        id_interno,
        id_solicitud,
        "CANCELADA",
        datos.motivo,
        ip_cliente(request.scope),
    )
