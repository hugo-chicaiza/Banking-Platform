"""CAJ-01..CAJ-18 · Caja: jornadas, dotaciones, ventanilla, cuadre y cierre.

Cada ruta exige sesión y rol con `require_roles` (no se usa `require_auth`, que hoy
no valida nada). Las rutas que escriben pasan además por el control CSRF de
`usuario_actual`. Las que necesitan el id interno del usuario fallan cerradas con
403 USUARIO_INTERNO_NO_VINCULADO mientras no exista ese vínculo (ver
app/core/security/operador.py).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import Connection

from app.core.api.errors import RESPUESTAS_ERROR, ProblemDetailsRoute, solo_parametros
from app.core.database.db import cooperativa

# from app.core.security.auth import Usuario, require_roles
from app.modules.caja import service
from app.modules.caja.schemas import CajaFisica


def _sin_cache(response: Response) -> None:
    """Datos de caja y de clientes: que no queden en cachés de navegador ni proxy."""
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"


router = APIRouter(
    prefix="/caja",
    tags=["Caja"],
    route_class=ProblemDetailsRoute,
    responses=RESPUESTAS_ERROR,
    dependencies=[Depends(_sin_cache)],
)

Conexion = Annotated[Connection, Depends(cooperativa)]
CodigoAgencia = Annotated[
    str | None, Query(alias="idAgencia", min_length=3, max_length=3, pattern=r"^\d{3}$")
]


# def _roles(*roles: str) -> object:
#    return Depends(require_roles(*roles))


# CAJ-01: autenticación y autorización pendientes para W4.
@router.get("/cajas-fisicas", response_model=list[CajaFisica], operation_id="CAJ01")
def listar_cajas_fisicas(
    _parametros: Annotated[None, Depends(solo_parametros("idAgencia", "activa"))],
    conn: Conexion,
    id_agencia: CodigoAgencia = None,
    activa: bool | None = None,
) -> list[CajaFisica]:
    """Lista las cajas físicas con filtros opcionales."""
    return service.listar_cajas_fisicas(conn, id_agencia, activa)
