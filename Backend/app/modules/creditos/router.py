from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy import Connection

from app.core.api.errors import RESPUESTAS_ERROR, ProblemDetailsRoute, solo_parametros
from app.core.database.db import cooperativa
from app.core.security.auth import require_auth, require_roles
from app.modules.creditos import service
from app.modules.creditos.schemas import (
    CondicionesCredito,
    Simulacion,
    SimulacionRequest,
)

router = APIRouter(
    tags=["creditos"],
    dependencies=[Depends(require_auth)],
)

Db = Annotated[Connection, Depends(cooperativa)]
IdTipoCredito = Annotated[int, Path(gt=0, le=2147483647)]

# ---------------------------------------------------------------------------
# CR-03 · Simulación de tabla de amortización
# ---------------------------------------------------------------------------
# Roles: ASESOR, ADMIN
_ROLES_SIMULACION = ["ASESOR", "ADMIN"]
_simulacion_router = APIRouter(
    route_class=ProblemDetailsRoute,
    responses=RESPUESTAS_ERROR,
    dependencies=[Depends(require_roles(*_ROLES_SIMULACION))],
)


@_simulacion_router.get(
    "/tipos/{idTipoCredito}/condiciones",
    operation_id="CRE01",
    response_model=CondicionesCredito,
    dependencies=[Depends(solo_parametros("monto", "plazoMeses"))],
    openapi_extra={"x-roles": _ROLES_SIMULACION},
)
def obtener_condiciones(
    idTipoCredito: IdTipoCredito,
    conn: Db,
    monto: Annotated[Decimal | None, Query(gt=0)] = None,
    plazo_meses: Annotated[int | None, Query(alias="plazoMeses", gt=0)] = None,
) -> CondicionesCredito:
    """CRE-01 · Tasa, plazo máximo, seguros e impuestos vigentes del tipo de crédito."""
    return service.obtener_condiciones(conn, idTipoCredito, monto, plazo_meses)


@_simulacion_router.post(
    "/simulaciones",
    operation_id="CRE02",
    response_model=Simulacion,
    openapi_extra={"x-roles": _ROLES_SIMULACION},
)
def simular(payload: SimulacionRequest, conn: Db) -> Simulacion:
    """CRE-02 · Simula la tabla de amortización (FRANCES o ALEMAN). No guarda nada."""
    return service.simular(conn, payload)


router.include_router(_simulacion_router, prefix="/creditos")
