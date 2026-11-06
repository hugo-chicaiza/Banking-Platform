"""DTO de Caja (OpenAPI `CAJ01`..`CAJ18`). camelCase en el JSON, Decimal en Python."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from pydantic import AfterValidator, ConfigDict, Field, StringConstraints
from pydantic.alias_generators import to_camel

from app.core.api.schemas import CamelModel, Money


# CAJ-01
class CajaFisica(CamelModel):
    id_caja_fisica: int
    id_agencia: str | None = None
    codigo_caja: str | None = None
    estado: bool | None = None
    descripcion_estado: str | None = None
    limite_efectivo_caja: Money | None = None


# --- CAJ-02: Consulta de jornadas ------------------------------------


class Jornada(CamelModel):
    id_jornada_caja: int
    id_usuario: int
    id_caja_fisica: int
    id_agencia: str
    fecha_hora_apertura: datetime
    fecha_hora_cierre: datetime | None = None
    dinero_inicial: Money
    estado: Literal["ABIERTA", "CERRADA", "CANCELADA"]
    observacion: str | None = None


class PageJornada(CamelModel):
    items: list[Jornada]
    page: int
    page_size: int
    total: int


# --- CAJ-05: tipos y validaciones compartidas ---

ZONA_ECUADOR = ZoneInfo("America/Guayaquil")
INT32_MAX = 2_147_483_647


def a_ecuador(valor: datetime) -> datetime:
    """Interpreta las fechas de la BD como hora local de Ecuador."""
    if valor.tzinfo is None:
        return valor.replace(tzinfo=ZONA_ECUADOR)
    return valor.astimezone(ZONA_ECUADOR)


FechaHoraEc = Annotated[datetime, AfterValidator(a_ecuador)]

MontoPositivo = Annotated[
    Decimal,
    Field(gt=0, max_digits=18, decimal_places=2),
]

MontoNoNegativo = Annotated[
    Decimal,
    Field(ge=0, max_digits=18, decimal_places=2),
]

IdInt = Annotated[int, Field(gt=0, le=INT32_MAX)]

Texto500 = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=500),
]


class Entrada(CamelModel):
    """Modelo base para validar cuerpos de petición."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        validate_by_name=True,
        extra="forbid",
    )


# --- CAJ-08: dotaciones de la jornada ----------


class Dotacion(CamelModel):
    id_dotacion_caja: int
    id_jornada_caja: int | None = None
    id_boveda: int | None = None
    tipo_dotacion: str | None = None
    monto: Money | None = None
    id_movimiento_boveda: int | None = None
    boveda_bajo_minimo: bool | None = None
    estado: str | None = None
