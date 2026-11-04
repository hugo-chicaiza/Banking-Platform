from datetime import date, datetime
from typing import Literal

from pydantic import ConfigDict, Field, field_validator
from pydantic.json_schema import SkipJsonSchema

from app.core.api.schemas import CamelModel, Money
from app.modules.tarjetas.schemas import Tarjeta

TipoDocumento = Literal["C", "R", "P"]
TipoCliente = Literal["Natural", "Juridico"]
Genero = Literal["M", "F"]
EstadoCivil = Literal["Soltero", "Casado", "Divorciado", "Viudo", "Union Libre"]
TipoDireccion = Literal["Domicilio", "Trabajo", "Correspondencia", "Otra"]
EstadoCliente = Literal[
    "Pendiente", "Activo", "Bloqueado", "Inactivo", "Cerrado", "Eliminado", "Suspendido"
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


class ClienteUpdate(CamelModel):
    """CLI-05: omitir conserva el valor; null solo borra campos anulables."""

    model_config = ConfigDict(extra="forbid")

    nombres: str | SkipJsonSchema[None] = Field(
        default=None, min_length=1, max_length=250
    )
    apellidos: str | None = Field(default=None, min_length=1, max_length=250)
    razon_social: str | None = Field(default=None, min_length=1, max_length=250)
    nombre_comercial: str | None = Field(default=None, min_length=1, max_length=250)
    id_actividad_economica: int | None = None
    estado_civil: EstadoCivil | None = None
    telefono_convencional: str | None = Field(default=None, max_length=15)
    telefono_celular: str | SkipJsonSchema[None] = Field(
        default=None, min_length=7, max_length=15
    )
    email: str | SkipJsonSchema[None] = Field(
        default=None,
        min_length=5,
        max_length=150,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
    )

    @field_validator("nombres", "telefono_celular", "email", mode="before")
    @classmethod
    def no_anulable(cls, valor: str | None) -> str:
        if valor is None:
            raise ValueError("El campo no admite null.")
        return valor

    @field_validator("nombres", "apellidos", "razon_social", "nombre_comercial")
    @classmethod
    def texto_no_vacio(cls, valor: str | None) -> str | None:
        if valor is not None and not valor.strip():
            raise ValueError("El campo no puede contener solo espacios.")
        return valor


class ClienteEstadoUpdate(CamelModel):
    """Contrato CLI-06; Observaciones es VARCHAR(500) en SQL Server."""

    model_config = ConfigDict(extra="forbid")

    estado: Literal["Activo", "Inactivo", "Suspendido", "Bloqueado", "Eliminado"]
    motivo: str = Field(min_length=1, max_length=500)

    @field_validator("motivo")
    @classmethod
    def motivo_no_vacio(cls, valor: str) -> str:
        if not valor.strip():
            raise ValueError("El motivo no puede contener solo espacios.")
        return valor


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


# CLI-13 / CLI-14 · Evaluaciones de riesgo
NivelRiesgoLAFT = Literal["Bajo", "Medio", "Alto"]
ResultadoEvaluacion = Literal["Aprobado", "Observado", "Rechazado"]


class RiesgoCreate(CamelModel):
    """Evaluación LAFT, PEP y antecedentes (CLI-13)."""

    nivel_riesgo_laft: NivelRiesgoLAFT = Field(alias="nivelRiesgoLAFT")
    es_pep: bool = Field(default=False, alias="esPEP")
    resultado_evaluacion: ResultadoEvaluacion
    tiene_antecedentes: bool = False
    id_tipo_antecedente: int | None = None
    observaciones: str | None = Field(default=None, max_length=250)


class Riesgo(RiesgoCreate):
    """Evaluación persistida, incluida su vigencia (CLI-14)."""

    id_evaluacion: int
    id_cliente: int
    fecha_evaluacion: datetime
    evaluador: int
    es_vigente: bool


class RiesgoRegistrado(Riesgo):
    """Evaluación y estado del cliente después del trigger (CLI-13)."""

    estado_cliente: EstadoCliente


class PageCliente(CamelModel):
    items: list[Cliente]
    page: int
    page_size: int
    total: int


class ClienteHistorial(CamelModel):
    """Registro inmutable de ClientesHis (CLI-07)."""

    id_historial: int
    tipo_operacion: str
    campo_modificado: str
    valor_anterior: str | None = None
    modificado_por: int
    direccion_ip: str = Field(alias="direccionIP")
    fecha_modificacion: datetime
    observaciones: str


class PageClienteHistorial(CamelModel):
    items: list[ClienteHistorial]
    page: int
    page_size: int
    total: int


class CuentaPerfil(CamelModel):
    id_cuenta: int
    numero_cuenta: str
    id_cliente: int
    id_agencia: str
    id_producto: int
    tipo_cuenta: str
    id_moneda: int
    saldo: Money
    saldo_retenido: Money
    saldo_disponible: Money
    estado: str
    fecha_apertura: datetime
    fecha_ultimo_movimiento: datetime | None = None
    fecha_cierre: datetime | None = None


class TarjetaPerfil(Tarjeta):
    """Datos de tarjeta con número enmascarado; nunca incluye PAN ni hash."""


class CreditoPerfil(CamelModel):
    id_solicitud: int
    numero_solicitud: str
    tipo_credito: str
    monto_desembolsado: Money | None = None
    saldo_capital: Money | None = None
    proxima_cuota: date | None = None
    estado: str


class ClientePerfil(CamelModel):
    cliente: Cliente
    riesgo_vigente: Riesgo | None = None
    cuentas: list[CuentaPerfil] = Field(default_factory=list)
    tarjetas: list[TarjetaPerfil] = Field(default_factory=list)
    creditos: list[CreditoPerfil] = Field(default_factory=list)
