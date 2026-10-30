from datetime import date, datetime
from typing import Literal

from pydantic import Field

from app.core.schemas import CamelModel


class DireccionCliente(CamelModel):
    id_direccion: int | None = None
    tipo_direccion: str | None = None
    codigo_pais: str | None = None
    id_ciudad: int | None = None
    sector: str | None = None
    calle_direccion: str | None = None
    referencia_ubicacion: str | None = None
    codigo_postal: str | None = None
    es_principal: bool | None = None
    estado: str | None = None


class Cliente(CamelModel):
    id_cliente: int
    identificacion: str
    tipo_documento: str
    tipo_cliente: Literal["Natural", "Juridico"]
    nombres: str
    apellidos: str | None = None
    id_actividad_economica: int | None = None
    fecha_nacimiento: date
    genero: str | None = None
    estado_civil: str | None = None
    codigo_pais_nacionalidad: str
    telefono_convencional: str | None = None
    telefono_celular: str
    email: str
    consentimiento_datos: bool
    fecha_consentimiento: datetime
    estado: str
    fecha_registro: datetime
    creado_por: int
    direcciones: list[DireccionCliente] = Field(default_factory=list)


class PageCliente(CamelModel):
    items: list[Cliente]
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    total: int = Field(ge=0)
