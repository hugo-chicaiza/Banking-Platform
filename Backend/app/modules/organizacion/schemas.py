"""Contratos de Organización · Agencias (ORG-01 POST, ORG-02 PATCH).

Columnas reales de Organizacion.Agencia (anexo B, consulta 1):
IdAgencia char(3) PK, Codigo varchar(10) único, TipoAgencia varchar(10)
(CK Matriz/Sucursal), Estado char(1) (CK A/I/C, default 'A'), Telefono varchar(15) NULL,
Direccion varchar(250) NULL, FechaCreacion datetime2 (default SQL), IdCiudad int (FK
Catalogo.Ciudad), KeyAgencia varchar(64) NULL (único si no es NULL).
"""

from datetime import date, datetime
from typing import Annotated, Literal, Self
from zoneinfo import ZoneInfo

from pydantic import (
    AfterValidator,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)
from pydantic.json_schema import SkipJsonSchema

from app.core.api.schemas import CamelModel

ZONA_ECUADOR = ZoneInfo("America/Guayaquil")
INT32_MAX = 2_147_483_647

TipoAgencia = Literal["Matriz", "Sucursal"]
# 'C' existe en CK_Agencia_Estado, pero su significado no está confirmado: la API no
# permite llegar a él ni salir de él (ver service._TRANSICIONES).
EstadoAgencia = Literal["A", "I", "C"]
EstadoSolicitado = Literal["A", "I"]

# Mismo juego de caracteres que los ejemplos reales (001, MTZ-UIO). No se infiere un
# algoritmo de numeración: el cliente envía el IdAgencia y la BD garantiza la unicidad.
IdAgencia = Annotated[str, StringConstraints(pattern=r"^[0-9A-Z]{3}$")]
Codigo = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=10, pattern=r"^[A-Z0-9-]+$"
    ),
]
Telefono = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=6, max_length=15, pattern=r"^[0-9+() -]+$"
    ),
]
# Sin caracteres de control: termina en reportes y en la auditoría
Direccion = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=250,
        pattern=r"^[^\x00-\x1f\x7f]+$",
    ),
]
IdCiudad = Annotated[int, Field(ge=1, le=INT32_MAX)]
# Organización de WorkOS vinculada a la agencia. auth ya no la usa: la agencia del usuario
# sale de Organizacion.Usuarios.AgenciaID (C-05). Formato de los ids: org_<alfanumérico>.
KeyAgencia = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=5,
        max_length=64,
        pattern=r"^org_[0-9A-Za-z]+$",
    ),
]
Motivo = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=300,
        pattern=r"^[^\x00-\x1f\x7f]+$",
    ),
]


def a_ecuador(valor: datetime) -> datetime:
    """FechaCreacion se guarda en hora de Ecuador sin desfase (default de la tabla)."""
    if valor.tzinfo is None:
        return valor.replace(tzinfo=ZONA_ECUADOR)
    return valor.astimezone(ZONA_ECUADOR)


class _Entrada(CamelModel):
    """Campos desconocidos (IdAgencia en el PATCH, FechaCreacion, Estado en el POST) son 400."""

    model_config = ConfigDict(extra="forbid", validate_by_name=False)


class AgenciaCreate(_Entrada):
    id_agencia: IdAgencia
    codigo: Codigo
    tipo_agencia: TipoAgencia
    id_ciudad: IdCiudad
    telefono: Telefono | None = None
    direccion: Direccion | None = None
    key_agencia: KeyAgencia | None = None


class AgenciaUpdate(_Entrada):
    """PATCH parcial: solo se cambian los campos presentes. null borra un opcional."""

    codigo: Codigo | None = None
    tipo_agencia: TipoAgencia | None = None
    estado: EstadoSolicitado | None = None
    id_ciudad: IdCiudad | None = None
    telefono: Telefono | None = None
    direccion: Direccion | None = None
    key_agencia: KeyAgencia | None = None
    # Obligatorio cuando cambia el estado: queda en la auditoría
    motivo: Motivo | None = None

    @model_validator(mode="after")
    def _validar(self) -> "AgenciaUpdate":
        campos = self.model_fields_set - {"motivo"}
        if not campos:
            raise ValueError("Envíe al menos un campo para actualizar.")
        for obligatorio in ("codigo", "tipo_agencia", "estado", "id_ciudad"):
            if obligatorio in campos and getattr(self, obligatorio) is None:
                raise ValueError(f"{obligatorio} no admite null.")
        if "estado" in campos and self.motivo is None:
            raise ValueError("motivo es obligatorio para cambiar el estado.")
        return self


class Agencia(CamelModel):
    id_agencia: str
    codigo: str
    tipo_agencia: TipoAgencia
    estado: EstadoAgencia
    id_ciudad: int
    telefono: str | None = None
    direccion: str | None = None
    fecha_creacion: Annotated[datetime, AfterValidator(a_ecuador)]
    # El valor de KeyAgencia no se publica: solo si la agencia tiene organización
    vinculada_workos: bool


# Contratos heredados: endpoint PATCH /agencias/{id_agencia}/estado.
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
