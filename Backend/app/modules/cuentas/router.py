from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Connection

from app.core.api.errors import RESPUESTAS_ERROR, ProblemDetailsRoute
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
    EstadoCuenta,
    PageCuenta,
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


# require_auth aún no valida la sesión; estos roles son metadatos hasta activar F-03.
_ROLES_CONSULTA = ["ASESOR", "CAJERO", "SUPERVISOR", "ADMIN"]
_consultas_router = APIRouter(
    route_class=ProblemDetailsRoute, responses=RESPUESTAS_ERROR
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
    """Busca cuentas por filtros exactos combinables (CTA-02 / A-02).

    Autorización efectiva pendiente de la activación de require_auth (F-03).
    """
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

    Autorización efectiva pendiente de la activación de require_auth (F-03).
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

    Autorización efectiva pendiente de la activación de require_auth (F-03).
    `idMoneda` es siempre 840 porque la cooperativa opera exclusivamente en USD.
    """
    return service.obtener_saldo(conn, idCuenta)


router.include_router(_apertura_router, prefix="/cuentas")
router.include_router(_consultas_router, prefix="/cuentas")
