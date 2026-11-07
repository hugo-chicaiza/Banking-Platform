from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, StrictBool, StrictInt, StringConstraints

from app.core.api.schemas import CamelModel

# Máximo de una columna int en SQL Server
MAX_INT = 2_147_483_647
MAX_PAGINA = 1_000_000
MAX_PAGE_SIZE = 100

IdEntero = Annotated[StrictInt, Field(gt=0, le=MAX_INT)]

TipoTarjeta = Literal["Debito", "Credito"]

# Valores de CK_Tarjeta_Estado
EstadoTarjeta = Literal[
    "Solicitada",
    "EnRevision",
    "Aprobada",
    "Rechazada",
    "Generada",
    "Pendiente",
    "Activa",
    "Inactiva",
    "Bloqueada",
    "Cancelada",
    "Vencida",
    "Anulada",
    "Cerrada",
]

# Estados que TAR-04 admite como destino
EstadoDestino = Literal[
    "Aprobada",
    "Generada",
    "Activa",
    "Inactiva",
    "Bloqueada",
    "Cancelada",
    "Anulada",
]


class _Entrada(CamelModel):
    """Base de los bodies: rechaza campos fuera del contrato y solo acepta camelCase."""

    model_config = ConfigDict(extra="forbid", validate_by_name=False)


class TarjetaCreate(_Entrada):
    """Body de POST /api/v1/tarjetas (TAR-01)."""

    id_cuenta: IdEntero
    id_producto: IdEntero
    tipo_tarjeta: TipoTarjeta
    nombre_tarjeta: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True,
            min_length=1,
            max_length=50,
            pattern=r"^[A-Za-zÁÉÍÓÚÜÑáéíóúüñ][A-Za-zÁÉÍÓÚÜÑáéíóúüñ .'\-]*$",
        ),
    ]
    es_extension: StrictBool = False
    id_tarjeta_titular: IdEntero | None = None
    requiere_envio: StrictBool = False
    direccion_envio: (
        Annotated[
            str,
            StringConstraints(
                strip_whitespace=True,
                min_length=1,
                max_length=250,
                pattern=r"^[^\x00-\x1f\x7f]+$",
            ),
        ]
        | None
    ) = None
    id_ciudad_envio: IdEntero | None = None


class TarjetaEstadoUpdate(_Entrada):
    """Body de POST /api/v1/tarjetas/{idTarjeta}/estado (TAR-04)."""

    estado: EstadoDestino
    motivo: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True,
            min_length=1,
            max_length=500,
            pattern=r"^[^\x00-\x1f\x7f]+$",
        ),
    ]


PATRON_PIN_BLOCK = r"^[0-9A-Fa-f]{32}$"
PATRON_REFERENCIA_CLAVE = r"^[A-Za-z0-9_-]{1,32}$"


class PinAsignar(_Entrada):
    """Solo documenta TAR-05 en OpenAPI. El router no valida con este modelo (un error
    de Pydantic devolvería el valor recibido): ver _leer_pin_block.
    """

    encrypted_pin_block: Annotated[
        str,
        Field(
            pattern=PATRON_PIN_BLOCK,
            description="PIN Block ISO 9564-1 formato 4 (AES-256), 16 bytes en hex",
        ),
    ]
    key_reference: Annotated[
        str,
        Field(
            pattern=PATRON_REFERENCIA_CLAVE,
            description="Referencia de la clave AES-256 autorizada en el servidor",
        ),
    ]


class PinBlockPruebaEntrada(_Entrada):
    """Solo documenta el PIN pad simulado en OpenAPI (ver _leer_pin_prueba)."""

    id_tarjeta: IdEntero
    pin: Annotated[str, Field(min_length=4, max_length=4, pattern=r"^[0-9]{4}$")]


class PinBlockPrueba(CamelModel):
    """Lo que el PIN pad simulado entrega para TAR-05 o ATM-01."""

    encrypted_pin_block: str
    key_reference: str


class TarjetaResumen(CamelModel):
    """Ítem de TAR-02. No incluye el token."""

    id_tarjeta: int
    id_cliente: int
    id_cuenta: int
    id_producto: int
    tipo_tarjeta: TipoTarjeta
    nombre_tarjeta: str
    numero_enmascarado: str
    estado_actual: EstadoTarjeta
    fecha_emision: date


class Tarjeta(TarjetaResumen):
    """Respuesta de TAR-01, TAR-03 y TAR-04."""

    token_tarjeta: str
    pin_asignado: bool
    fecha_expiracion: date


class PageTarjeta(CamelModel):
    items: list[TarjetaResumen]
    page: int
    page_size: int
    total: int


class TarjetaHistorial(CamelModel):
    """Evento de TAR-06. No incluye IP ni canal."""

    id_historial: int
    id_tarjeta: int
    tipo_evento: str
    estado_anterior: str | None = None
    estado_nuevo: str | None = None
    motivo: str | None = None
    resultado: str | None = None
    fecha_cambio: datetime
    realizado_por: int


class PageTarjetaHistorial(CamelModel):
    items: list[TarjetaHistorial]
    page: int
    page_size: int
    total: int
