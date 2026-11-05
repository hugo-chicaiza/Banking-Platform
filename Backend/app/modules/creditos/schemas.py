from datetime import date
from decimal import Decimal
from enum import StrEnum

from pydantic import ConfigDict, Field

from app.core.api.schemas import CamelModel, Money

# CRE-01 · Condiciones vigentes de un tipo de crédito


class RubroCredito(CamelModel):
    """Un seguro o un impuesto que aplica al tipo de crédito."""

    id: int
    codigo: str
    nombre: str
    tipo_calculo: str  # "Fijo" o "Porcentaje"
    valor: Money
    obligatorio: bool


class CondicionesCredito(CamelModel):
    """Tasa vigente, plazo máximo, seguros e impuestos de un tipo de crédito."""

    id_tipo_credito: int
    tasa_nominal_anual: Money
    plazo_maximo_meses: int
    recargo_mora_sobre_tasa: Money
    monto_minimo: Money | None
    monto_maximo: Money | None
    seguros: list[RubroCredito]
    impuestos: list[RubroCredito]


# CRE-02 · Simulación de la tabla de amortización


class SistemaAmortizacion(StrEnum):
    FRANCES = "FRANCES"  # cuota fija
    ALEMAN = "ALEMAN"  # capital fijo


class SimulacionRequest(CamelModel):
    """Body de POST /api/v1/creditos/simulaciones (CRE-02)."""

    model_config = ConfigDict(extra="forbid", validate_by_name=False)

    id_tipo_credito: int = Field(gt=0, le=2147483647)
    monto: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    plazo_meses: int = Field(gt=0, le=600)
    sistema_amortizacion: SistemaAmortizacion
    fecha_primer_vencimiento: date | None = None


class CuotaSimulada(CamelModel):
    numero: int
    vencimiento: date
    saldo_inicial: Money
    capital: Money
    interes: Money
    total_seguros: Money
    total_impuestos: Money
    valor: Money  # capital + interés + seguros + impuestos
    saldo_final: Money


class Simulacion(CamelModel):
    tasa_nominal_anual: Money
    cuota_referencial: Money  # valor de la primera cuota
    total_intereses: Money
    total_seguros: Money
    total_impuestos: Money
    costo_total: Money  # suma de todas las cuotas (total a pagar)
    plan: list[CuotaSimulada]
