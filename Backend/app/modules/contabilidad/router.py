from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy import Connection

from app.core.api.errors import RESPUESTAS_ERROR, ProblemDetailsRoute, solo_parametros
from app.core.database.db import cooperativa
from app.core.security.auth import require_auth, require_roles
from app.modules.contabilidad import service
from app.modules.contabilidad.schemas import CuentaContable, FechaContable

router = APIRouter(
    prefix="/contabilidad",
    tags=["contabilidad"],
    dependencies=[Depends(require_auth)],
)

Db = Annotated[Connection, Depends(cooperativa)]

# ---------------------------------------------------------------------------
# AC-02 · Fecha contable
# ---------------------------------------------------------------------------
# Roles: AUTH (cualquier usuario autenticado)
# OJO: /fechas-contables/actual debe declararse ANTES que /fechas-contables/{fecha};
# si no, FastAPI tomaría "actual" como si fuera una fecha.


@router.get("/fechas-contables/actual", response_model=FechaContable)
def fecha_contable_actual(conn: Db) -> Any:
    """CON-02 · Fecha contable vigente (según la hora de corte de las 19:00)."""
    return service.obtener_fecha_contable_actual(conn)


@router.get("/fechas-contables/{fecha}", response_model=FechaContable)
def fecha_contable_por_fecha(
    conn: Db,
    fecha: Annotated[str, Path(description="Día calendario, formato YYYY-MM-DD")],
) -> Any:
    """CON-01 · Fila del calendario contable de una fecha (día hábil, feriado, corte)."""
    return service.obtener_fecha_contable(conn, fecha)


# ---------------------------------------------------------------------------
# AC-03 · Plan de cuentas
# ---------------------------------------------------------------------------
# Roles: CONTADOR, AUDITOR, ADMIN
_ROLES_CUENTAS_CONTABLES = ["CONTADOR", "AUDITOR", "ADMIN"]
_cuentas_contables_router = APIRouter(
    route_class=ProblemDetailsRoute,
    responses=RESPUESTAS_ERROR,
    dependencies=[Depends(require_roles(*_ROLES_CUENTAS_CONTABLES))],
)


@_cuentas_contables_router.get(
    "/cuentas-contables",
    operation_id="CON03",
    response_model=list[CuentaContable],
    dependencies=[Depends(solo_parametros("q", "imputable"))],
    openapi_extra={"x-roles": _ROLES_CUENTAS_CONTABLES},
)
def listar_cuentas_contables(
    conn: Db,
    q: Annotated[
        str | None,
        Query(min_length=1, max_length=100, description="Código o nombre"),
    ] = None,
    imputable: Annotated[
        bool | None, Query(description="Solo las cuentas imputables")
    ] = None,
) -> Any:
    """CON-03 · Plan de cuentas (CUC), con filtro por texto y por imputable.

    Implementación parcial: responde 501 hasta que se agregue la consulta a la BD.
    """
    return service.listar_cuentas_contables(conn, q, imputable)


router.include_router(_cuentas_contables_router)
