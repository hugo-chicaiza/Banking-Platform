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
