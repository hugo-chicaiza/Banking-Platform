from typing import Literal
from pydantic import Field
from app.core.schemas import CamelModel, Money


TipoCuenta = Literal["Ahorro", "Corriente"]

EstadoCuenta = Literal[
    "PENDIENTE_ACTIVACION",
    "ACTIVA",
    "INACTIVA",
    "BLOQUEADA",
    "CERRADA",
]

# CTA-01 · Creación de cuenta


class CuentaCreate(CamelModel):
    """Body de POST /api/v1/cuentas (CTA-01)."""

    id_cliente: int
    id_producto: int
    id_agencia: str = Field(min_length=1, max_length=3)
    tipo_cuenta: TipoCuenta
    id_moneda: int = 840  # Por defecto dolares


# Respuesta de cuenta

class Cuenta(CamelModel):
    """Representación de una cuenta bancaria devuelta por el API."""

    id_cuenta: int
    numero_cuenta: str
    id_cliente: int
    id_producto: int
    id_agencia: str
    tipo_cuenta: TipoCuenta
    id_moneda: int
    saldo: Money
    saldo_retenido: Money
    estado: EstadoCuenta
