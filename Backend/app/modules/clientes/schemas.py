from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import ConfigDict, Field, StringConstraints, field_validator
from pydantic.json_schema import SkipJsonSchema

from app.core.api.schemas import CamelModel, Money
from app.modules.cuentas.schemas import EstadoCuenta, MonedaUsd
from app.modules.tarjetas.schemas import Tarjeta

TipoDocumento = Literal["C", "R", "P"]
TipoCliente = Literal["Natural", "Juridico"]
Genero = Literal["M", "F"]
EstadoCivil = Literal["Soltero", "Casado", "Divorciado", "Viudo", "Union Libre"]
TipoDireccion = Annotated[
    str, Field(min_length=1, max_length=20, pattern=r"^[^\x00-\x1f\x7f]+$")
]
EstadoCliente = Literal[
    "Pendiente", "Activo", "Bloqueado", "Inactivo", "Cerrado", "Eliminado", "Suspendido"
]
EstadoDireccion = Literal["Activo", "Inactivo", "Eliminado"]

TextoCliente = Annotated[
    str, StringConstraints(min_length=1, max_length=250, pattern=r"\S")
]
EmailCliente = Annotated[
    str, Field(min_length=5, max_length=150, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
]
CodigoPostal = Annotated[str, Field(min_length=6, max_length=6, pattern=r"^[0-9]{6}$")]

# ---------------------------------------------------------------------------
# CLI-01 · Validación de identificación
# ---------------------------------------------------------------------------


class ValidacionDocumentoBody(CamelModel):
    """Body de POST /api/v1/clientes/validaciones/documento (CLI-01)."""

    model_config = ConfigDict(extra="forbid")

    tipo_documento: TipoDocumento
    identificacion: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=13)
    ]


class ValidacionIdentificacion(CamelModel):
    """Respuesta de POST /api/v1/clientes/validaciones/documento (CLI-01)."""

    valida: bool
    existe: bool
    id_cliente: int | None = None
    mensaje: str
    reincorporable: bool = False
    estado: str | None = None


# ---------------------------------------------------------------------------
# CLI-02 · Registro de cliente
# ---------------------------------------------------------------------------


class DireccionCreate(CamelModel):
    """Dirección principal enviada en el alta de cliente (CLI-02)."""

    model_config = ConfigDict(extra="forbid")

    tipo_direccion: TipoDireccion = "Domicilio"
    codigo_pais: str = Field(default="ECU", min_length=3, max_length=3)
    id_ciudad: int
    sector: str | None = Field(default=None, max_length=50)
    calle_direccion: TextoCliente
    referencia_ubicacion: TextoCliente
    codigo_postal: CodigoPostal | None = None
    es_principal: Literal[True] = True


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

    model_config = ConfigDict(extra="forbid")

    identificacion: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=13)
    ]
    tipo_documento: TipoDocumento
    tipo_cliente: TipoCliente
    nombres: TextoCliente
    apellidos: TextoCliente | None = None
    razon_social: TextoCliente | None = None
    nombre_comercial: TextoCliente | None = None
    id_actividad_economica: int | None = None
    fecha_nacimiento: date
    genero: Genero | None = None
    estado_civil: EstadoCivil | None = None
    codigo_pais_nacionalidad: str = Field(default="ECU", min_length=3, max_length=3)
    telefono_convencional: str | None = Field(default=None, max_length=15)
    telefono_celular: str = Field(min_length=7, max_length=15)
    email: EmailCliente
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
    motivo_estado: str | None = None
    fecha_registro: datetime
    creado_por: int
    direcciones: list[Direccion]
    # E5-04: marca manual "verificado por el personal" del correo principal.
    email_verificado: bool = False
    fecha_email_verificado: datetime | None = None
    # E5-05: agencia donde se registró (NULL en clientes anteriores sin dato).
    id_agencia_registro: str | None = None


Identificacion = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=13)
]
IdEntero = Annotated[int, Field(gt=0, le=2147483647)]

# E5-04: los ordinarios se aplican al instante; los sensibles los aprueba otra persona.
CAMPOS_ORDINARIOS = frozenset(
    {
        "nombre_comercial",
        "id_actividad_economica",
        "estado_civil",
        "telefono_convencional",
        "telefono_celular",
    }
)
CAMPOS_SENSIBLES = frozenset(
    {
        "nombres",
        "apellidos",
        "razon_social",
        "fecha_nacimiento",
        "tipo_documento",
        "identificacion",
        "email",
    }
)
# Un cambio de nombre o documento exige respaldo cuando CLI_EXIGE_ARCHIVOS está activo.
CAMPOS_CON_RESPALDO = frozenset(
    {"nombres", "apellidos", "razon_social", "tipo_documento", "identificacion"}
)
_NO_ANULABLES = (
    "nombres",
    "telefono_celular",
    "email",
    "fecha_nacimiento",
    "tipo_documento",
    "identificacion",
)


def _no_nulo(valor: Any) -> Any:
    if valor is None:
        raise ValueError("El campo no admite null.")
    return valor


def _texto_no_vacio(valor: str | None) -> str | None:
    if valor is not None and not valor.strip():
        raise ValueError("El campo no puede contener solo espacios.")
    return valor


class ClienteUpdate(CamelModel):
    """CLI-05: omitir conserva el valor; null solo borra campos anulables."""

    model_config = ConfigDict(extra="forbid")

    nombres: TextoCliente | SkipJsonSchema[None] = None
    apellidos: TextoCliente | None = None
    razon_social: TextoCliente | None = None
    nombre_comercial: TextoCliente | None = None
    id_actividad_economica: int | None = None
    estado_civil: EstadoCivil | None = None
    telefono_convencional: str | None = Field(default=None, max_length=15)
    telefono_celular: str | SkipJsonSchema[None] = Field(
        default=None, min_length=7, max_length=15
    )
    email: EmailCliente | SkipJsonSchema[None] = None
    fecha_nacimiento: date | SkipJsonSchema[None] = None
    tipo_documento: TipoDocumento | SkipJsonSchema[None] = None
    identificacion: Identificacion | SkipJsonSchema[None] = None
    # Archivo de E5-08 que respalda un cambio de nombre o documento.
    id_archivo_respaldo: IdEntero | None = None

    @field_validator(*_NO_ANULABLES, mode="before")
    @classmethod
    def no_anulable(cls, valor: Any) -> Any:
        return _no_nulo(valor)

    @field_validator("nombres", "apellidos", "razon_social", "nombre_comercial")
    @classmethod
    def texto_no_vacio(cls, valor: str | None) -> str | None:
        return _texto_no_vacio(valor)


class CambiosSensibles(CamelModel):
    """Campos sensibles congelados en la solicitud de E0-08 (E5-04)."""

    model_config = ConfigDict(extra="forbid")

    nombres: TextoCliente | None = None
    apellidos: TextoCliente | None = None
    razon_social: TextoCliente | None = None
    fecha_nacimiento: date | None = None
    tipo_documento: TipoDocumento | None = None
    identificacion: Identificacion | None = None
    email: EmailCliente | None = None

    @field_validator(
        *(c for c in _NO_ANULABLES if c != "telefono_celular"), mode="before"
    )
    @classmethod
    def no_anulable(cls, valor: Any) -> Any:
        return _no_nulo(valor)

    @field_validator("nombres", "apellidos", "razon_social")
    @classmethod
    def texto_no_vacio(cls, valor: str | None) -> str | None:
        return _texto_no_vacio(valor)


class ContenidoEdicion(CamelModel):
    """Contenido de CLI-EDITAR; el autor y su IP se fijan en el servidor."""

    model_config = ConfigDict(extra="forbid")

    cambios: CambiosSensibles
    id_archivo_respaldo: IdEntero | None = None
    modificado_por: IdEntero
    direccion_ip: str = Field(min_length=1, max_length=45)

    @field_validator("cambios")
    @classmethod
    def con_cambios(cls, valor: CambiosSensibles) -> CambiosSensibles:
        if not valor.model_fields_set:
            raise ValueError("La solicitud no contiene cambios.")
        return valor


class ClienteEstadoUpdate(CamelModel):
    """Contrato CLI-06; MotivoEstado es VARCHAR(300) en SQL Server."""

    model_config = ConfigDict(extra="forbid")

    estado: Literal["Activo", "Inactivo", "Suspendido", "Bloqueado", "Eliminado"]
    motivo: str = Field(min_length=1, max_length=300)

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

    model_config = ConfigDict(extra="forbid")

    tipo_direccion: TipoDireccion = "Domicilio"
    codigo_pais: str = Field(default="ECU", min_length=3, max_length=3)
    id_ciudad: int
    sector: str | None = Field(default=None, max_length=50)
    calle_direccion: TextoCliente
    referencia_ubicacion: TextoCliente
    codigo_postal: CodigoPostal | None = None
    es_principal: bool = False


class DireccionUpdate(CamelModel):
    """Body de PATCH /api/v1/clientes/{idCliente}/direcciones/{idDireccion} (CLI-11).

    Todos los campos son opcionales para soportar patch parcial.
    """

    model_config = ConfigDict(extra="forbid")

    tipo_direccion: TipoDireccion | SkipJsonSchema[None] = None
    codigo_pais: str | SkipJsonSchema[None] = Field(
        default=None, min_length=3, max_length=3
    )
    id_ciudad: int | SkipJsonSchema[None] = None
    sector: str | None = Field(default=None, max_length=50)
    calle_direccion: TextoCliente | SkipJsonSchema[None] = None
    referencia_ubicacion: TextoCliente | SkipJsonSchema[None] = None
    codigo_postal: CodigoPostal | None = None
    es_principal: bool | SkipJsonSchema[None] = None

    @field_validator(
        "tipo_direccion",
        "codigo_pais",
        "id_ciudad",
        "calle_direccion",
        "referencia_ubicacion",
        "es_principal",
        mode="before",
    )
    @classmethod
    def no_anulable(cls, valor: Any) -> Any:
        if valor is None:
            raise ValueError("El campo no admite null.")
        return valor


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
    vigente_hasta: date | None = None
    id_solicitud: int | None = None


class ContenidoRiesgo(CamelModel):
    """Contenido congelado en la solicitud de CLI-RIESGO (E5-06)."""

    model_config = ConfigDict(extra="forbid")

    nivel_riesgo_laft: NivelRiesgoLAFT = Field(alias="nivelRiesgoLAFT")
    es_pep: bool = Field(default=False, alias="esPEP")
    resultado_evaluacion: ResultadoEvaluacion = Field(alias="resultadoEvaluacion")
    tiene_antecedentes: bool = False
    id_tipo_antecedente: int | None = None
    observaciones: str | None = Field(default=None, max_length=250)
    evaluador: IdEntero
    direccion_ip: str = Field(min_length=1, max_length=45)


class RiesgoRegistrado(Riesgo):
    """Evaluación y estado del cliente después del trigger (CLI-13)."""

    estado_cliente: EstadoCliente


CodigoAgencia = Annotated[str, Field(pattern=r"^[0-9]{3}$")]
TextoBusqueda = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=3,
        max_length=100,
        pattern=r"^[^\x00-\x1f\x7f]+$",
    ),
]
OrdenCliente = Annotated[str, Field(max_length=40)]


class ClienteBusqueda(CamelModel):
    """E5-05 · Filtros en el cuerpo: documento, nombre y correo nunca van en la URL
    ni en los registros (ASVS 14.2.1)."""

    model_config = ConfigDict(extra="forbid")

    identificacion: Identificacion | None = None
    # Coincide con el inicio de cualquier palabra de nombres, apellidos o razón social.
    nombre: TextoBusqueda | None = None
    email: EmailCliente | None = None
    estado: EstadoCliente | None = None
    id_agencia_registro: CodigoAgencia | None = None
    tipo_cliente: TipoCliente | None = None
    page: int = Field(default=1, ge=1, le=10000)
    page_size: int = Field(default=20, ge=1, le=100)
    sort: OrdenCliente | None = None

    @field_validator("email")
    @classmethod
    def email_minusculas(cls, valor: str | None) -> str | None:
        return None if valor is None else valor.lower()

    def tiene_filtro(self) -> bool:
        # El tipo de cliente solo acota: por sí solo devolvería media cartera.
        filtros = (
            self.identificacion,
            self.nombre,
            self.email,
            self.estado,
            self.id_agencia_registro,
        )
        return any(f is not None for f in filtros)


CampoRevelable = Literal[
    "identificacion",
    "email",
    "telefonoCelular",
    "telefonoConvencional",
    "correosSecundarios",
]


class DesafioRevelacion(CamelModel):
    """Desafío MFA de WorkOS para el factor TOTP del usuario de la sesión."""

    id_desafio: str | None = None
    expira_en: str | None = None  # ISO 8601 tal como lo da WorkOS
    # False mientras REVELACION_EXIGE_MFA esté apagado: se revela sin código.
    requiere_codigo: bool = True


class SolicitudRevelacion(CamelModel):
    model_config = ConfigDict(extra="forbid")

    campos: list[CampoRevelable] = Field(min_length=1, max_length=5)
    id_desafio: str | None = Field(
        default=None, min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_]+$"
    )
    codigo: str | None = Field(default=None, pattern=r"^[0-9]{6}$")

    @field_validator("campos")
    @classmethod
    def sin_repetidos(cls, valor: list[str]) -> list[str]:
        if len(set(valor)) != len(valor):
            raise ValueError("Cada campo se pide una sola vez.")
        return valor


class Revelacion(CamelModel):
    """Solo los campos pedidos; los demás quedan null."""

    identificacion: str | None = None
    email: str | None = None
    telefono_celular: str | None = None
    telefono_convencional: str | None = None
    correos_secundarios: list[str] | None = None


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
    valor_nuevo: str | None = None
    modificado_por: int
    direccion_ip: str = Field(alias="direccionIP")
    fecha_modificacion: datetime
    observaciones: str
    # Solicitud E0-08 que aprobó el cambio sensible (E5-04).
    id_solicitud: int | None = None


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
    id_moneda: MonedaUsd
    saldo: Money
    saldo_retenido: Money
    saldo_disponible: Money
    estado: EstadoCuenta
    fecha_apertura: datetime
    fecha_ultimo_movimiento: datetime | None = None
    fecha_cierre: datetime | None = None

    @field_validator("estado", mode="before")
    @classmethod
    def estado_publico(cls, valor: str) -> str:
        return valor.upper()


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


# ---------------------------------------------------------------------------
# E5-04 · Correos del cliente
# ---------------------------------------------------------------------------


class ClienteEmailNuevo(CamelModel):
    """Body de POST /api/v1/clientes/{idCliente}/emails."""

    model_config = ConfigDict(extra="forbid")

    email: EmailCliente
    etiqueta: Annotated[
        str, Field(min_length=1, max_length=30, pattern=r"^[^\x00-\x1f\x7f]+$")
    ]

    @field_validator("email")
    @classmethod
    def email_minusculas(cls, valor: str) -> str:
        return valor.lower()

    @field_validator("etiqueta")
    @classmethod
    def etiqueta_con_texto(cls, valor: str) -> str:
        if not valor.strip():
            raise ValueError("La etiqueta no puede quedar vacía.")
        return valor


class ClienteEmail(CamelModel):
    """Correo secundario activo; quién lo creó o verificó queda solo en la base."""

    id_cliente_email: int
    email: str
    etiqueta: str
    verificado: bool
    fecha_verificacion: datetime | None = None
    fecha_creacion: datetime


class VerificacionEmail(CamelModel):
    """Marca manual del personal sobre el correo principal (no se envía correo)."""

    email_verificado: bool
    fecha_email_verificado: datetime
