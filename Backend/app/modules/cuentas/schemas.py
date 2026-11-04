from typing import Literal

from pydantic import AwareDatetime, Field

from app.core.api.schemas import CamelModel, Money

TipoCuenta = Literal["Ahorro", "Corriente"]
MonedaUsd = Literal[840]
ID_MONEDA_USD: MonedaUsd = 840

EstadoCuenta = Literal[
    "ACTIVA",
    "INACTIVA",
    "BLOQUEADA",
    "CERRADA",
]

# CTA-01 · Creación de cuenta


class CuentaCreate(CamelModel):
    """Body de POST /api/v1/cuentas (CTA-01)."""

    id_cliente: int
    id_sub_producto: int
    id_agencia: str = Field(min_length=3, max_length=3)
    monto_inicial: Money = Field(ge=0)
    id_moneda: MonedaUsd = ID_MONEDA_USD


# Respuesta de cuenta


class Cuenta(CamelModel):
    """Representación de una cuenta bancaria devuelta por el API."""

    id_cuenta: int
    numero_cuenta: str
    id_cliente: int
    id_producto: int
    id_agencia: str
    tipo_cuenta: TipoCuenta
    id_moneda: MonedaUsd
    saldo: Money
    saldo_retenido: Money
    estado: EstadoCuenta


class CuentaResumen(CamelModel):
    """Datos de identificación y estado del listado CTA-02."""

    id_cuenta: int
    numero_cuenta: str
    id_cliente: int
    id_producto: int
    id_agencia: str
    tipo_cuenta: TipoCuenta
    estado: EstadoCuenta


class PageCuenta(CamelModel):
    items: list[CuentaResumen]
    page: int
    page_size: int
    total: int


class SaldoCuenta(CamelModel):
    id_cuenta: int
    saldo: Money
    saldo_retenido: Money
    saldo_disponible: Money
    id_moneda: MonedaUsd
    fecha_consulta: AwareDatetime
