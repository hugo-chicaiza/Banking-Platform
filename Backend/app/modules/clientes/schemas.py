from datetime import date, datetime
from typing import Literal

from pydantic import Field

from app.core.schemas import CamelModel

TipoDocumento = Literal["C", "R", "P"]
TipoCliente = Literal["Natural", "Juridico"]
Genero = Literal["M", "F"]
EstadoCivil = Literal["Soltero", "Casado", "Divorciado", "Viudo", "Union Libre"]
TipoDireccion = Literal["Domicilio", "Trabajo", "Correspondencia", "Otra"]
EstadoCliente = Literal[
    "Pendiente", "Activo", "Bloqueado", "Inactivo", "Cerrado", "Eliminado"
]
EstadoDireccion = Literal["Activo", "Inactivo", "Eliminado"]

# ---------------------------------------------------------------------------
# CLI-01 · Validación de identificación
# ---------------------------------------------------------------------------


class ValidacionIdentificacion(CamelModel):
    """Respuesta de GET /api/v1/clientes/validar-identificacion (CLI-01)."""

    valida: bool
    existe: bool
    id_cliente: int | None = None
    mensaje: str


# ---------------------------------------------------------------------------
# CLI-02 · Registro de cliente
# ---------------------------------------------------------------------------


class DireccionCreate(CamelModel):
    """Dirección principal enviada en el alta de cliente (CLI-02)."""

    tipo_direccion: TipoDireccion = "Domicilio"
    codigo_pais: str = Field(default="ECU", min_length=3, max_length=3)
    id_ciudad: int
    sector: str | None = None
    calle_direccion: str = Field(min_length=1)
    referencia_ubicacion: str = Field(min_length=1)
    codigo_postal: str | None = Field(default=None, min_length=6, max_length=6)
    es_principal: bool = True


class Direccion(CamelModel):
    """Representación de una dirección devuelta por el API."""

    id_direccion: int
    tipo_direccion: TipoDireccion
    codigo_pais: str
    id_ciudad: int
    sector: str | None = None
    calle_direccion: str
    referencia_ubicacion: str
    codigo_postal: str | None = None
    es_principal: bool
    estado: str = "Activo"


class ClienteCreate(CamelModel):
    """Body de POST /api/v1/clientes (CLI-02)."""

    identificacion: str = Field(min_length=1, max_length=13)
    tipo_documento: TipoDocumento
    tipo_cliente: TipoCliente
    nombres: str = Field(min_length=1)
    apellidos: str | None = None
    razon_social: str | None = None
    nombre_comercial: str | None = None
    id_actividad_economica: int | None = None
    fecha_nacimiento: date
    genero: Genero | None = None
    estado_civil: EstadoCivil | None = None
    codigo_pais_nacionalidad: str = Field(default="ECU", min_length=3, max_length=3)
    telefono_convencional: str | None = Field(default=None, max_length=15)
    telefono_celular: str = Field(min_length=7, max_length=15)
    email: str = Field(min_length=5, max_length=150)
    consentimiento_datos: bool
    direccion: DireccionCreate


class Cliente(CamelModel):
    """Representación de un cliente devuelto por el API (CLI-02, CLI-04)."""

    id_cliente: int
    identificacion: str
    tipo_documento: TipoDocumento
    tipo_cliente: TipoCliente
    nombres: str
    apellidos: str | None = None
    razon_social: str | None = None
    nombre_comercial: str | None = None
    id_actividad_economica: int | None = None
    fecha_nacimiento: date
    genero: Genero | None = None
    estado_civil: EstadoCivil | None = None
    codigo_pais_nacionalidad: str
    telefono_convencional: str | None = None
    telefono_celular: str
    email: str
    consentimiento_datos: bool
    fecha_consentimiento: datetime
    estado: str
    fecha_registro: datetime
    creado_por: int
    direcciones: list[Direccion]


# ---------------------------------------------------------------------------
# Administración de direcciones del cliente
# ---------------------------------------------------------------------------


class DireccionNueva(CamelModel):
    """Body de POST /api/v1/clientes/{idCliente}/direcciones (CLI-10)."""

    tipo_direccion: TipoDireccion = "Domicilio"
    codigo_pais: str = Field(default="ECU", min_length=3, max_length=3)
    id_ciudad: int
    sector: str | None = None
    calle_direccion: str = Field(min_length=1)
    referencia_ubicacion: str = Field(min_length=1)
    codigo_postal: str | None = Field(
        default=None, min_length=6, max_length=6, pattern=r"^\d{6}$"
    )
    es_principal: bool = False


class DireccionUpdate(CamelModel):
    """Body de PATCH /api/v1/clientes/{idCliente}/direcciones/{idDireccion} (CLI-11).

    Todos los campos son opcionales para soportar patch parcial.
    """

    tipo_direccion: TipoDireccion | None = None
    codigo_pais: str | None = Field(default=None, min_length=3, max_length=3)
    id_ciudad: int | None = None
    sector: str | None = None
    calle_direccion: str | None = Field(default=None, min_length=1)
    referencia_ubicacion: str | None = Field(default=None, min_length=1)
    codigo_postal: str | None = Field(
        default=None, min_length=6, max_length=6, pattern=r"^\d{6}$"
    )
    es_principal: bool | None = None
