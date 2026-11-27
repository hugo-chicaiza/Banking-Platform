"""Contrato de solicitudes. Las identidades se obtienen de la sesión."""

from typing import Annotated, Literal

from pydantic import ConfigDict, Field, StringConstraints, model_validator

from app.core.api.schemas import CamelModel, Money
from app.modules.boveda.schemas import (
    Desglose,
    EntradaDesglose,
    FechaEc,
    IdInt,
    TipoOperacion,
)

EstadoSolicitud = Literal[
    "PENDIENTE",
    "APROBADO",
    "DESPACHADO",
    "RECIBIDO",
    "DEVUELTO",
    "EJECUTADA",
    "RECHAZADA",
    "CANCELADA",
    "ANULADA",
]
Referencia = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=100),
]


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


class DespachoRequest(ConfirmacionRequest):
    numero_guia: Referencia | None = None
    precinto: Referencia | None = None

    @model_validator(mode="after")
    def documentos_completos(self):
        if (self.numero_guia is None) != (self.precinto is None):
            raise ValueError("Indique tanto la guía como el precinto.")
        return self


class ConteoRequest(DespachoRequest):
    desglose: Annotated[list[Desglose], Field(max_length=100)]

    @model_validator(mode="after")
    def sin_duplicados(self):
        ids = [d.id_denominacion for d in self.desglose]
        if len(ids) != len(set(ids)):
            raise ValueError("El desglose repite una denominación.")
        return self


class RecepcionRequest(ConteoRequest):
    acta_novedad: Referencia | None = None


class DevolucionRequest(ConteoRequest):
    acta_novedad: Referencia


class CierreRequest(ConfirmacionRequest):
    comprobante_banco: Referencia


class DestinoBoveda(CamelModel):
    id_boveda: int
    codigo_boveda: str
    id_agencia: str


class DetalleSolicitud(CamelModel):
    id_denominacion: int
    cantidad: int
    valor_unitario: Money


class SolicitudMovimiento(CamelModel):
    id_solicitud_movimiento: int
    id_boveda: int
    id_boveda_contraparte: int | None
    id_agencia: str
    id_agencia_destino: str | None = None
    tipo_movimiento: TipoOperacion
    monto: Money
    id_usuario_solicitante: int
    fecha_solicitud: FechaEc
    estado: EstadoSolicitud
    observaciones: str | None
    id_usuario_resolucion: int | None
    fecha_resolucion: FechaEc | None
    motivo_resolucion: str | None
    id_usuario_anulacion: int | None = None
    fecha_anulacion: FechaEc | None = None
    motivo_anulacion: str | None = None
    id_usuario_despacho: int | None = None
    fecha_despacho: FechaEc | None = None
    numero_guia: str | None = None
    precinto: str | None = None
    id_usuario_confirmacion: int | None = None
    fecha_confirmacion: FechaEc | None = None
    monto_confirmado: Money | None = None
    diferencia: Money | None = None
    acta_novedad: str | None = None
    comprobante_banco: str | None = None
    id_asiento_despacho: int | None = None
    id_asiento_confirmacion: int | None = None
    id_asiento_novedad: int | None = None
    conteo_confirmado: list[DetalleSolicitud] = Field(default_factory=list)
    desglose: list[DetalleSolicitud]
    ids_movimientos: list[int]


class PageSolicitudMovimiento(CamelModel):
    items: list[SolicitudMovimiento]
    page: int
    page_size: int
    total: int
