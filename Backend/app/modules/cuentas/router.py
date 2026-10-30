from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import Connection

from app.core.db import cooperativa
from app.core.security import require_auth
from app.modules.cuentas import service
from app.modules.cuentas.schemas import Cuenta, CuentaCreate

router = APIRouter(
    prefix="/cuentas",
    tags=["cuentas"],
    dependencies=[Depends(require_auth)],
)

Db = Annotated[Connection, Depends(cooperativa)]

# ---------------------------------------------------------------------------
# CTA-01 · POST /api/v1/cuentas
# ---------------------------------------------------------------------------
# Roles: ASESOR, ADMIN
# TODO(F-03): restringir por rol cuando require_auth valide el JWT.
#             Hasta entonces el endpoint NO debe considerarse listo para producción.


@router.post("", response_model=Cuenta, status_code=201)
def abrir_cuenta(payload: CuentaCreate, conn: Db) -> Any:
    """Abre una cuenta para un cliente activo (CTA-01 / A-01).

    **Nota de autenticación (F-03):** `require_auth()` todavía no valida el
    JWT de WorkOS.  El `creado_por` se fija temporalmente a `"sistema"`;
    cuando F-03 esté implementado se leerá del token.
    """
    # TODO(F-03): extraer el sub/email del JWT validado como creado_por
    creado_por = "sistema"
    return service.abrir_cuenta(conn, payload, creado_por)
