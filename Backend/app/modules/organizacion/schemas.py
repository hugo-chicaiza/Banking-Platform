from datetime import date, datetime
from typing import Literal, Self

from pydantic import ConfigDict, Field, field_validator, model_validator
from pydantic.json_schema import SkipJsonSchema

from app.core.api.schemas import CamelModel

EstadoAgencia = Literal["A", "I", "C"]


class AgenciaEstadoUpdate(CamelModel):
    model_config = ConfigDict(extra="forbid")
    estado: EstadoAgencia


class AgenciaEstado(CamelModel):
    id_agencia: str
    estado: EstadoAgencia


EstadoEntidad = Literal["A", "I"]


class Entidad(CamelModel):
    """Datos persistidos de la única entidad, incluidos los campos de auditoría."""

    id_entidad: int
    ruc: str
    razon_social: str
    nombre_comercial: str | None
    tipo_organizacion: str
    segmento: int | None
    numero_resolucion_seps: str | None
    fecha_constitucion: date
    representante_legal: str
    identificacion_representante: str
    telefono: str | None
    email: str | None
    sitio_web: str | None
    estado: EstadoEntidad
    fecha_registro: datetime
    modificado_por: int


class EntidadUpdate(CamelModel):
    """Omitir conserva el valor. null vacía exclusivamente columnas anulables."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "minProperties": 1,
            "examples": [
                {"nombreComercial": "Cooperativa Ejemplo", "telefono": "022345678"}
            ],
        },
    )

    ruc: str | SkipJsonSchema[None] = Field(
        default=None, min_length=13, max_length=13, pattern=r"^[0-9]{10}001$"
    )
    razon_social: str | SkipJsonSchema[None] = Field(
        default=None, min_length=1, max_length=250, pattern=r"\S"
    )
    nombre_comercial: str | None = Field(default=None, max_length=150)
    tipo_organizacion: str | SkipJsonSchema[None] = Field(
        default=None, min_length=1, max_length=60, pattern=r"\S"
    )
    segmento: int | None = Field(default=None, strict=True, ge=1, le=5)
    numero_resolucion_seps: str | None = Field(default=None, max_length=60)
    fecha_constitucion: date | SkipJsonSchema[None] = None
    representante_legal: str | SkipJsonSchema[None] = Field(
        default=None, min_length=1, max_length=250, pattern=r"\S"
    )
    identificacion_representante: str | SkipJsonSchema[None] = Field(
        default=None, min_length=5, max_length=13, pattern=r"^[0-9A-Z]{5,13}$"
    )
    telefono: str | None = Field(default=None, max_length=15)
    email: str | None = Field(default=None, max_length=150)
    sitio_web: str | None = Field(default=None, max_length=150)
    estado: EstadoEntidad | SkipJsonSchema[None] = None

    @field_validator(
        "ruc",
        "razon_social",
        "tipo_organizacion",
        "fecha_constitucion",
        "representante_legal",
        "identificacion_representante",
        "estado",
        mode="before",
    )
    @classmethod
    def no_anulable(cls, valor: object) -> object:
        if valor is None:
            raise ValueError("El campo no admite null.")
        return valor

    @model_validator(mode="after")
    def exigir_campos(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("Envíe al menos un campo para actualizar.")
        return self
