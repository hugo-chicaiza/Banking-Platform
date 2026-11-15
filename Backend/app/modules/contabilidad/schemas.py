from datetime import date, time

from app.core.api.schemas import CamelModel, Money

# CON-01 / CON-02 · Fecha contable


class FechaContable(CamelModel):
    """Una fila del calendario contable (Contabilidad.FechaContable)."""

    id_fecha_contable: int
    fecha: date
    es_dia_contable: bool
    es_feriado: bool
    es_fin_de_semana: bool
    hora_corte: time  # se serializa como HH:mm:ss


# CON-03 · Plan de cuentas (CUC)


class CuentaContable(CamelModel):
    """Una cuenta del plan de cuentas (Contabilidad.CuentasContables)."""

    id_cuenta_contable: int
    codigo_cuenta: str
    nombre_cuenta: str
    naturaleza: str  # "DEUDORA" o "ACREEDORA"
    tipo_cuenta: str
    id_cuenta_superior: int | None  # None en las cuentas de primer nivel
    es_imputable: bool  # solo las imputables reciben movimientos
    saldo: Money
    estado: str


# CON-04 / CON-05 · Asientos contables

INT32_MAX = 2_147_483_647


class MovimientoAsiento(CamelModel):
    """Una línea del asiento (Contabilidad.MovimientosContables)."""

    id_movimiento_contable: int
    id_cuenta_contable: int
    codigo_cuenta: str
    tipo_movimiento: str  # "DEBITO" o "CREDITO"
    monto: Money
    id_transaccion: int | None
    id_agencia: str | None


class Asiento(CamelModel):
    """Cabecera de Contabilidad.AsientoContable con su detalle.

    En CON-04 `detalle` va vacío; el detalle completo se pide a CON-05.
    """

    id_asiento_contable: int
    numero_asiento: str
    fecha_asiento: date
    id_tipo_asiento: int
    origen: str
    concepto: str
    total_debito: Money
    total_credito: Money
    estado: str
    id_asiento_reversion: int | None
    id_agencia: str
    detalle: list[MovimientoAsiento]


class PageAsiento(CamelModel):
    items: list[Asiento]
    page: int
    page_size: int
    total: int
