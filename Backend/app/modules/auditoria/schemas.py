"""Esquemas de la bitácora de auditoría (E8-01)."""

from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import ConfigDict, Field, StringConstraints

from app.core.api.schemas import CamelModel

Resultado = Literal["Exitoso", "Fallido"]
FormatoExportacion = Literal["csv", "pdf"]

# Texto corto seguro (sin controles)
_TextoCorto = Annotated[
    str, StringConstraints(max_length=100, pattern=r"^[^\x00-\x1f\x7f]*$")
]
_TextoMedio = Annotated[
    str, StringConstraints(max_length=200, pattern=r"^[^\x00-\x1f\x7f]*$")
]


class FiltrosBusqueda(CamelModel):
    """Filtros de búsqueda de eventos de auditoría."""

    model_config = ConfigDict(extra="forbid")

    desde: date | None = None
    hasta: date | None = None
    usuario: Annotated[int, Field(ge=1)] | None = None
    agencia: Annotated[str, Field(pattern=r"^\d{3}$")] | None = None
    modulo: _TextoCorto | None = None
    codigo_evento: _TextoCorto | None = None
    resultado: Resultado | None = None
    tipo_objetivo: _TextoCorto | None = None
    id_objetivo: _TextoCorto | None = None
    origen: _TextoMedio | None = None
    canal: _TextoCorto | None = None
    correlacion: (
        Annotated[str, StringConstraints(max_length=64, pattern=r"^[^\x00-\x1f\x7f]*$")]
        | None
    ) = None
    id_solicitud: Annotated[int, Field(ge=1)] | None = None
    page: Annotated[int, Field(ge=1)] = 1
    page_size: Annotated[int, Field(ge=1, le=100)] = 25


class FiltrosExportacion(FiltrosBusqueda):
    """Filtros de exportación (mismos + formato)."""

    formato: FormatoExportacion = "csv"


class EventoItem(CamelModel):
    """Evento de auditoría en listado."""

    id: int
    id_evento: str | None = None
    codigo_evento: str | None = None
    modulo: str | None = None
    severidad: str | None = None
    fecha_hora_utc: datetime | None = None
    fecha_hora_local: datetime | None = None
    usuario: int | None = None
    nombre_usuario: str | None = None
    agencia: str | None = None
    canal: str | None = None
    origen: str | None = None
    resultado: str | None = None
    tipo_objetivo: str | None = None
    id_objetivo: str | None = None
    correlacion: str | None = None
    descripcion: str | None = None
    formato_anterior: bool = False


class PageEventos(CamelModel):
    """Página de eventos."""

    items: list[EventoItem]
    total: int
    page: int
    page_size: int


class Persona(CamelModel):
    """Solicitante o aprobador."""

    nombre: str | None = None
    id_interno: int | None = None


class Aprobacion(CamelModel):
    """Datos de aprobación vinculada a un evento."""

    id_solicitud: int
    operacion: str | None = None
    estado: str | None = None
    solicitante: Persona | None = None
    fecha_solicitud: datetime | None = None
    aprobador: Persona | None = None
    fecha_resolucion: datetime | None = None


class EventoDetalle(EventoItem):
    """Detalle completo de un evento."""

    cambios: Any | None = None
    aprobacion: Aprobacion | None = None
    relacionados: list[EventoItem] = Field(default_factory=list)


class TipoEvento(CamelModel):
    """Tipo de evento del catálogo."""

    codigo: str
    modulo: str
    severidad: str


class RangoVerificacion(CamelModel):
    """E8-02: días de la institución a verificar; el rango va en el cuerpo y es obligatorio."""

    model_config = ConfigDict(extra="forbid")

    desde: date | None = None
    hasta: date | None = None


class Verificacion(CamelModel):
    id_verificacion: int
    secuencia_desde: int
    secuencia_hasta: int
    resultado: Literal["Integra", "Rota"]
    primera_rota: int | None = None
    ejecutada_por: int | None = None
    fecha_utc: datetime


class PageVerificaciones(CamelModel):
    items: list[Verificacion]
    total: int
    page: int
    page_size: int
