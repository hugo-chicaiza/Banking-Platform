"""Reglas de negocio de Caja. Cada operación que escribe es una sola transacción de
BD (`with conn.begin()`): si algo falla, se revierte todo."""

from sqlalchemy import Connection

from app.core.api.errors import problema
from app.core.security.auth import Usuario
from app.core.security.operador import exigir_agencia
from app.modules.caja import repository as repo
from app.modules.caja.repository import Fila
from app.modules.caja.schemas import CajaFisica

# Roles que ven datos de cualquier agencia (solo lectura, según la matriz de roles)
ROLES_GLOBALES = frozenset({"CONTADOR", "AUDITOR", "ADMIN"})


def agencia_consultable(
    usuario: Usuario, pedida: str | None, roles_globales: frozenset[str]
) -> str | None:
    """Agencia que puede consultar el usuario.

    Con rol global: la pedida (None = todas). Sin él: la propia; pedir otra es 403.
    """
    if set(usuario.roles) & roles_globales:
        return pedida
    propia = exigir_agencia(usuario)
    if pedida is not None and pedida != propia:
        raise problema(
            403, "SIN_ACCESO_AGENCIA", "No tiene acceso a los datos de esa agencia."
        )
    return propia


def _caja(fila: Fila) -> CajaFisica:
    return CajaFisica(
        id_caja_fisica=fila["IdCajaFisica"],
        id_agencia=fila["IdAgencia"],
        codigo_caja=fila["CodigoCaja"],
        estado=fila["Estado"],
        descripcion_estado=fila["DescripcionEstado"],
        limite_efectivo_caja=fila["LimiteEfectivoCaja"],
    )


# --- CAJ-01 --------------------------------------------------------------------------


def listar_cajas_fisicas(
    conn: Connection,
    id_agencia: str | None,
    activa: bool | None,
) -> list[CajaFisica]:
    """Consulta cajas físicas. Autorización pendiente para W4."""
    return [_caja(f) for f in repo.listar_cajas_fisicas(conn, id_agencia, activa)]
