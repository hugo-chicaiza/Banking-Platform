from datetime import date, time

from app.core.api.schemas import CamelModel

# CON-01 / CON-02 · Fecha contable


class FechaContable(CamelModel):
    """Una fila del calendario contable (Contabilidad.FechaContable)."""

    id_fecha_contable: int
    fecha: date
    es_dia_contable: bool
    es_feriado: bool
    es_fin_de_semana: bool
    hora_corte: time  # se serializa como HH:mm:ss
