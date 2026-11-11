from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request
from sqlalchemy import Connection

from app.core.api.errors import RESPUESTAS_ERROR, ProblemDetailsRoute, solo_parametros
from app.core.api.middleware import ip_cliente, obtener_trace_id
from app.core.database.db import cooperativa
from app.core.security.auth import (
    Usuario,
    UsuarioAuditoria,
    require_auth,
    require_roles,
)
from app.modules.cuentas import service
from app.modules.cuentas.schemas import (
    Cuenta,
    CuentaCreate,
    CuentaEstadoUpdate,
    CupoEfectivo,
    CupoUpdate,
    EstadoCuenta,
    PageCuenta,
    PageCupoHistorial,
    PageMovimientoCuenta,
    SaldoCuenta,
)

router = APIRouter(
    tags=["cuentas"],
    dependencies=[Depends(require_auth)],
)

Db = Annotated[Connection, Depends(cooperativa)]
AperturadorCuenta = Annotated[Usuario, Depends(require_roles("ASESOR", "ADMIN"))]

# ---------------------------------------------------------------------------
# CTA-01 · POST /api/v1/cuentas
# ---------------------------------------------------------------------------
# Roles: ASESOR, ADMIN
_apertura_router = APIRouter(
    route_class=ProblemDetailsRoute, responses=RESPUESTAS_ERROR
)


@_apertura_router.post(
    "",
    operation_id="CTA01",
    response_model=Cuenta,
    status_code=201,
    openapi_extra={"x-roles": ["ASESOR", "ADMIN"]},
)
def abrir_cuenta(
    payload: CuentaCreate,
    usuario: AperturadorCuenta,
    creado_por: UsuarioAuditoria,
    conn: Db,
) -> Cuenta:
    """Abre una cuenta Activa mediante la firma real de usp_AbrirCuenta."""
    return service.abrir_cuenta(conn, payload, creado_por)


_ROLES_CONSULTA = ["ASESOR", "CAJERO", "SUPERVISOR", "ADMIN"]
_consultas_router = APIRouter(
    route_class=ProblemDetailsRoute,
    responses=RESPUESTAS_ERROR,
    dependencies=[Depends(require_roles(*_ROLES_CONSULTA))],
)


@_consultas_router.get(
    "",
    operation_id="CTA02",
    response_model=PageCuenta,
    openapi_extra={"x-roles": _ROLES_CONSULTA},
)
def listar_cuentas(
    conn: Db,
    id_cliente: Annotated[int | None, Query(alias="idCliente")] = None,
    numero_cuenta: Annotated[str | None, Query(alias="numeroCuenta")] = None,
    estado: EstadoCuenta | None = None,
    id_agencia: Annotated[
        str | None, Query(alias="idAgencia", min_length=3, max_length=3)
    ] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=100)] = 20,
    sort: str | None = None,
) -> PageCuenta:
    """Busca cuentas por filtros exactos combinables (CTA-02 / A-02)."""
    return service.listar_cuentas(
        conn,
        id_cliente=id_cliente,
        numero_cuenta=numero_cuenta,
        estado=estado,
        id_agencia=id_agencia,
        page=page,
        page_size=page_size,
        sort=sort,
    )


@_consultas_router.get(
    "/{idCuenta}",
    operation_id="CTA03",
    response_model=Cuenta,
    openapi_extra={"x-roles": _ROLES_CONSULTA},
)
def obtener_cuenta(idCuenta: int, conn: Db) -> Cuenta:
    """Detalle de cuenta en cualquier estado (CTA-03 / A-02).

    `idMoneda` es siempre 840 porque la cooperativa opera exclusivamente en USD.
    """
    return service.obtener_cuenta(conn, idCuenta)


@_consultas_router.get(
    "/{idCuenta}/saldo",
    operation_id="CTA04",
    response_model=SaldoCuenta,
    openapi_extra={"x-roles": _ROLES_CONSULTA},
)
def obtener_saldo(idCuenta: int, conn: Db) -> SaldoCuenta:
    """Saldo contable, retenido y disponible de la cuenta (CTA-04 / A-02).

    `idMoneda` es siempre 840 porque la cooperativa opera exclusivamente en USD.
    """
    return service.obtener_saldo(conn, idCuenta)


@_consultas_router.get(
    "/{idCuenta}/movimientos",
    operation_id="CTA06",
    response_model=PageMovimientoCuenta,
    dependencies=[
        Depends(
            solo_parametros(
                "desde", "hasta", "tipoTransaccion", "page", "pageSize", "sort"
            )
        )
    ],
    openapi_extra={"x-roles": _ROLES_CONSULTA},
)
def listar_movimientos(
    idCuenta: Annotated[int, Path(gt=0, le=2147483647)],
    conn: Db,
    desde: date,
    hasta: date,
    tipo_transaccion: Annotated[
        str | None, Query(alias="tipoTransaccion", min_length=1, max_length=30)
    ] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=100)] = 20,
    sort: Annotated[str | None, Query(max_length=40)] = None,
) -> PageMovimientoCuenta:
    """Movimientos propios de la cuenta, por fecha contable inclusiva (CTA-06)."""
    return service.listar_movimientos(
        conn,
        idCuenta,
        desde=desde,
        hasta=hasta,
        tipo_transaccion=tipo_transaccion,
        page=page,
        page_size=page_size,
        sort=sort,
    )


router.include_router(_apertura_router, prefix="/cuentas")
router.include_router(_consultas_router, prefix="/cuentas")


_ROLES_ESTADO_CUPOS = ["ASESOR", "SUPERVISOR", "ADMIN"]
_ROLES_MODIFICAR_CUPO = ["SUPERVISOR", "ADMIN"]
_ROLES_HISTORIAL_CUPO = ["SUPERVISOR", "AUDITOR", "ADMIN"]
GestorEstadoCupos = Annotated[Usuario, Depends(require_roles(*_ROLES_ESTADO_CUPOS))]
GestorCupo = Annotated[Usuario, Depends(require_roles(*_ROLES_MODIFICAR_CUPO))]
AuditorCupo = Annotated[Usuario, Depends(require_roles(*_ROLES_HISTORIAL_CUPO))]
IdRecurso = Annotated[int, Path(gt=0, le=2147483647)]
_gestion_router = APIRouter(
    route_class=ProblemDetailsRoute,
    responses={
        **RESPUESTAS_ERROR,
        503: {**RESPUESTAS_ERROR[500], "description": "Service Unavailable"},
    },
)


@_gestion_router.patch(
    "/{idCuenta}/estado",
    operation_id="CTA05",
    response_model=Cuenta,
    dependencies=[Depends(solo_parametros())],
    openapi_extra={"x-roles": _ROLES_ESTADO_CUPOS},
)
def cambiar_estado_cuenta(
    idCuenta: IdRecurso,
    payload: CuentaEstadoUpdate,
    request: Request,
    usuario: GestorEstadoCupos,
    modificado_por: UsuarioAuditoria,
    conn: Db,
) -> Cuenta:
    """Cambia el estado con bloqueo transaccional y auditoría del usuario de sesión."""
    return service.cambiar_estado_cuenta(
        conn,
        idCuenta,
        payload,
        modificado_por,
        ip_cliente(request.scope),
        obtener_trace_id(request.scope),
    )


@_gestion_router.get(
    "/{idCuenta}/cupos",
    operation_id="CTA07",
    response_model=list[CupoEfectivo],
    dependencies=[Depends(solo_parametros())],
    openapi_extra={"x-roles": _ROLES_ESTADO_CUPOS},
)
def obtener_cupos(
    idCuenta: IdRecurso, usuario: GestorEstadoCupos, conn: Db
) -> list[CupoEfectivo]:
    """Cupos vigentes y consumo en Ecuador para los roles internos publicados."""
    return service.obtener_cupos(conn, idCuenta)


@_gestion_router.put(
    "/{idCuenta}/cupos/{idCanal}",
    operation_id="CTA08",
    response_model=CupoEfectivo,
    dependencies=[Depends(solo_parametros())],
    openapi_extra={"x-roles": _ROLES_MODIFICAR_CUPO},
)
def actualizar_cupo(
    idCuenta: IdRecurso,
    idCanal: IdRecurso,
    payload: CupoUpdate,
    usuario: GestorCupo,
    modificado_por: UsuarioAuditoria,
    conn: Db,
) -> CupoEfectivo:
    """Guarda cupo e historial en una transacción y devuelve el cupo vigente."""
    return service.actualizar_cupo(conn, idCuenta, idCanal, payload, modificado_por)


@_gestion_router.get(
    "/{idCuenta}/cupos/{idCanal}/historial",
    operation_id="CTA09",
    response_model=PageCupoHistorial,
    dependencies=[Depends(solo_parametros("page", "pageSize", "sort"))],
    openapi_extra={"x-roles": _ROLES_HISTORIAL_CUPO},
)
def obtener_historial_cupo(
    idCuenta: IdRecurso,
    idCanal: IdRecurso,
    usuario: AuditorCupo,
    conn: Db,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=100)] = 20,
    sort: Annotated[
        str | None,
        Query(
            max_length=40,
            description="fechaModificacion o idCupoModHis, seguido de ,asc o ,desc",
        ),
    ] = None,
) -> PageCupoHistorial:
    return service.obtener_historial_cupo(
        conn,
        idCuenta,
        idCanal,
        page=page,
        page_size=page_size,
        sort=sort,
    )


router.include_router(_gestion_router, prefix="/cuentas")
