"""Contrato de solicitudes. Las identidades se obtienen de la sesión."""

from typing import Annotated, Literal

from pydantic import ConfigDict, Field, StringConstraints, model_validator

from app.core.api.schemas import CamelModel, Money
from app.modules.boveda.schemas import EntradaDesglose, FechaEc, IdInt, TipoOperacion

EstadoSolicitud = Literal["PENDIENTE", "EJECUTADA", "RECHAZADA", "CANCELADA"]


class SolicitudMovimientoRequest(EntradaDesglose):
    tipo_movimiento: TipoOperacion
    id_boveda_contraparte: IdInt | None = None
    observaciones: Annotated[str, Field(max_length=300)] | None = None

    @model_validator(mode="after")
    def cantidades_positivas(self):
        if any(d.cantidad == 0 for d in self.desglose):
            raise ValueError("Las cantidades deben ser positivas.")
        return self


class ResolucionRequest(CamelModel):
    model_config = ConfigDict(extra="forbid")
    motivo: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)
    ]


class ConfirmacionRequest(CamelModel):
    model_config = ConfigDict(extra="forbid")


class DetalleSolicitud(CamelModel):
    id_denominacion: int
    cantidad: int
    valor_unitario: Money


class SolicitudMovimiento(CamelModel):
    id_solicitud_movimiento: int
    id_boveda: int
    id_boveda_contraparte: int | None
    id_agencia: str
    tipo_movimiento: TipoOperacion
    monto: Money
    id_usuario_solicitante: int
    fecha_solicitud: FechaEc
    estado: EstadoSolicitud
    observaciones: str | None
    id_usuario_resolucion: int | None
    fecha_resolucion: FechaEc | None
    motivo_resolucion: str | None
    desglose: list[DetalleSolicitud]
    ids_movimientos: list[int]


class PageSolicitudMovimiento(CamelModel):
    items: list[SolicitudMovimiento]
    page: int
    page_size: int
    total: int
