"""DTO de Transacciones (OpenAPI `TRX01`..`TRX03`)."""

from app.core.api.schemas import CamelModel, Money
from app.modules.caja.schemas import FechaHoraEc


class Transaccion(CamelModel):
    """`idTerminal` sale de Transaccion.IdATM (la tabla no tiene IdTerminal).

    TRX-02: el esquema vigente no define colecciones de comisiones ni movimientos;
    se agregarán cuando el contrato las defina (pendiente de la ficha).
    """

    id_transaccion: int
    numero_comprobante: str | None = None
    registro_unico: str | None = None
    mti: str | None = None
    stan: str | None = None
    rrn: str | None = None
    tipo_operacion: str | None = None
    tipo_transaccion: str | None = None
    id_cuenta: int | None = None
    id_cuenta_destino: int | None = None
    id_tarjeta: int | None = None
    id_canal: int | None = None
    id_terminal: int | None = None
    id_agencia: str | None = None
    id_jornada_caja: int | None = None
    id_transaccion_relacionada: int | None = None
    monto: Money | None = None
    codigo_respuesta: str | None = None
    estado: str | None = None
    id_fecha_contable: int | None = None
    fecha_hora_sistema: FechaHoraEc | None = None
    creado_por: int | None = None


class PageTransaccion(CamelModel):
    items: list[Transaccion]
    page: int
    page_size: int
    total: int
