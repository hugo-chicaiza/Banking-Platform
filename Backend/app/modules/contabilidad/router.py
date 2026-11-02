from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path
from sqlalchemy import Connection

from app.core.db import cooperativa
from app.core.security import require_auth
from app.modules.contabilidad import service
from app.modules.contabilidad.schemas import FechaContable

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
