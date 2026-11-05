from datetime import date
from typing import Annotated, Literal

from pydantic import AwareDatetime, ConfigDict, Field, StringConstraints

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


class CuentaEstadoUpdate(CamelModel):
    model_config = ConfigDict(extra="forbid", validate_by_name=False)

    estado: EstadoCuenta
    # Auditoria.Descripcion tiene 500 caracteres; se reserva espacio para estados y traceId.
    motivo: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True,
            min_length=1,
            max_length=300,
            pattern=r"^[^\x00-\x1f\x7f]+$",
        ),
    ]


class CupoUpdate(CamelModel):
    """Límites positivos según CK_CanalCupoClienteCustom_Cupos de la base actual."""

    model_config = ConfigDict(extra="forbid", validate_by_name=False)

    cupo_diario: Money = Field(gt=0, max_digits=18, decimal_places=2)
    cupo_mensual: Money = Field(gt=0, max_digits=18, decimal_places=2)
    monto_max_transaccion: Money = Field(gt=0, max_digits=18, decimal_places=2)
    max_transacciones_dia: int = Field(strict=True, gt=0, le=32767)
    fecha_vigencia: date | None = Field(
        default=None,
        description="Último día de vigencia, inclusivo, en Ecuador; null no caduca.",
    )


class CupoEfectivo(CamelModel):
    id_canal: int
    origen: Literal["Personalizado", "Producto"]
    cupo_diario: Money
    cupo_mensual: Money
    monto_max_transaccion: Money
    max_transacciones_dia: int
    fecha_vigencia: date | None
    consumido_hoy: Money
    consumido_mes: Money


class CupoHistorial(CamelModel):
    id_cupo_mod_his: int
    cupo_diario_anterior: Money | None
    cupo_diario_nuevo: Money | None
    cupo_mensual_anterior: Money | None
    cupo_mensual_nuevo: Money | None
    monto_max_tx_anterior: Money | None
    monto_max_tx_nuevo: Money | None
    modificado_por: int
    fecha_modificacion: AwareDatetime


class PageCupoHistorial(CamelModel):
    items: list[CupoHistorial]
    page: int
    page_size: int
    total: int
