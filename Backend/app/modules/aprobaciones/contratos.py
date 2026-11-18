"""Contratos E0-08; el actor, los roles y la agencia se resuelven en el servidor."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import ConfigDict, Field, field_validator

from app.core.api.schemas import CamelModel

IdSolicitud = Annotated[int, Field(gt=0, le=9223372036854775807)]


class EstadoSolicitud(StrEnum):
    PENDIENTE = "Pendiente"
    APROBADA = "Aprobada"
    EJECUTADA = "Ejecutada"
    RECHAZADA = "Rechazada"
    CANCELADA = "Cancelada"
    FALLIDA = "Fallida"


class Rechazo(CamelModel):
    model_config = ConfigDict(extra="forbid")
    comentario: str = Field(min_length=1, max_length=300)

    @field_validator("comentario")
    @classmethod
    def obligatorio(cls, valor: str) -> str:
        valor = valor.strip()
        if not valor:
            raise ValueError("El comentario es obligatorio.")
        return valor


class Aprobacion(CamelModel):
    model_config = ConfigDict(extra="forbid")
    comentario: str | None = Field(default=None, max_length=300)


class SolicitudAceptada(CamelModel):
    id_solicitud: IdSolicitud
    estado: Literal["Pendiente"] = "Pendiente"
    requiere_aprobacion: Literal[True] = True


class Responsable(CamelModel):
    sujeto: str
    nombre: str | None = None
    id_interno: int | None = None


class SolicitudResumen(CamelModel):
    id_solicitud: IdSolicitud
    codigo_transaccion: str
    tipo_objetivo: str
    id_objetivo: str
    id_agencia: str | None
    estado: EstadoSolicitud
    fecha_solicitud: datetime
    solicitante: Responsable
    resolutor: Responsable | None = None
    fecha_resolucion: datetime | None = None
    comentario: str | None = None
    codigo_error: str | None = None
    puede_aprobar: bool = False
    puede_rechazar: bool = False
    puede_cancelar: bool = False


class EventoSolicitud(CamelModel):
    estado_anterior: EstadoSolicitud | None
    estado_nuevo: EstadoSolicitud
    responsable: Responsable | None
    comentario: str | None
    fecha_evento: datetime


class SolicitudDetalle(SolicitudResumen):
    antes: dict[str, Any]
    despues: dict[str, Any]
    eventos: list[EventoSolicitud]


class Bandeja(CamelModel):
    items: list[SolicitudResumen]
    total: int
    page: int
    page_size: int
    pendientes_para_mi: int
    dias_resaltar: int
