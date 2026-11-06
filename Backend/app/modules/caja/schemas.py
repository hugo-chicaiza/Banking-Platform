"""DTO de Caja (OpenAPI `CAJ01`..`CAJ18`). camelCase en el JSON, Decimal en Python."""

from datetime import datetime
from typing import Literal

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
