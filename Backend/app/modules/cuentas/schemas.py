from datetime import date
from typing import Annotated, Literal

from pydantic import (
    AwareDatetime,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
)

from app.core.api.schemas import CamelModel, Money

TipoCuenta = Literal["Ahorro", "Corriente"]
MonedaUsd = Literal[840]
ID_MONEDA_USD: MonedaUsd = 840

EstadoCuenta = Literal[
    "ACTIVA",
    "INACTIVA",
    "BLOQUEADA",
    "CERRADA",
    "PendienteDeposito",
    "Anulada",
]

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


class CuentaPendienteCreate(CamelModel):
    model_config = ConfigDict(extra="forbid", validate_by_name=False)
    id_cliente: int = Field(gt=0, le=2147483647)
    id_sub_producto: int = Field(gt=0, le=2147483647)


class AnularApertura(CamelModel):
    model_config = ConfigDict(extra="forbid")
    motivo: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=300),
    ]


class AutorizadoCuenta(CamelModel):
    id_cuenta_autorizado: int
    id_cliente_autorizado: int
    rol: Literal["Tutor", "RepresentanteLegal", "Firmante"]
    fecha_inicio: date
    fecha_fin: date | None
    vigente: bool


class AutorizadoCuentaCreate(CamelModel):
    model_config = ConfigDict(extra="forbid")
    id_cliente_autorizado: int = Field(gt=0, le=2147483647)
    rol: Literal["Tutor", "RepresentanteLegal", "Firmante"]


class EventoCuenta(CamelModel):
    id_cuenta_evento: int
    tipo_evento: str
    estado_anterior: str | None
    estado_actual: str
    detalle: str
    realizado_por: int
    id_agencia: str
    fecha_evento: AwareDatetime


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


class MovimientoCuenta(CamelModel):
    id_movimiento: int
    id_transaccion: int
    numero_comprobante: str | None
    tipo_transaccion: str
    tipo_movimiento: Literal["C", "D"]
    rol_cuenta: Literal["Origen", "Destino"] | None
    monto: Money
    saldo_anterior: Money
    saldo_posterior: Money
    fecha_contable: date
    fecha_hora_sistema: AwareDatetime
    id_canal: int | None


class PageMovimientoCuenta(CamelModel):
    items: list[MovimientoCuenta]
    page: int
    page_size: int
    total: int


class CuentaEstadoUpdate(CamelModel):
    model_config = ConfigDict(extra="forbid", validate_by_name=False)

    estado: Literal["ACTIVA", "INACTIVA", "BLOQUEADA", "CERRADA"]
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


class CupoSolicitado(CupoUpdate):
    solicitado_por_cliente: Literal[True]
    documento_verificado: Literal["C", "R", "P"]

    @field_validator("solicitado_por_cliente", mode="before")
    @classmethod
    def confirmar_pedido(cls, valor: object) -> object:
        if valor is not True:
            raise ValueError("Debe confirmar el pedido del cliente.")
        return valor


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
    tope_diario_producto: Money | None = None
    tope_mensual_producto: Money | None = None
    tope_transaccion_producto: Money | None = None
    tope_frecuencia_producto: int | None = None


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
    solicitado_por_cliente: bool | None = None
    documento_verificado: Literal["C", "R", "P"] | None = None


class PageCupoHistorial(CamelModel):
    items: list[CupoHistorial]
    page: int
    page_size: int
    total: int
