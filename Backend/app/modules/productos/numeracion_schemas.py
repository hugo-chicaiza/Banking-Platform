"""Formato de numeracion E3-04; el contador nunca procede del cliente."""

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, StringConstraints

from app.core.api.schemas import CamelModel


class ReglaEntrada(CamelModel):
    model_config = ConfigDict(extra="forbid")

    prefijo: Annotated[str, StringConstraints(pattern=r"^[0-9]{1,6}$")]
    incluye_agencia: Annotated[bool, Field(strict=True)] = False
    longitud_secuencia: Annotated[int, Field(strict=True, ge=6, le=10)] = 8
    algoritmo_verificador: Literal["NINGUNO", "MODULO_10", "MODULO_11"] = "NINGUNO"


class ReglaVista(ReglaEntrada):
    id_regla_numeracion: int
    usada: bool
    vigencia_desde: date
    vigencia_hasta: date | None
    fecha_creacion: datetime
    id_solicitud: int | None
    estado: Literal["A", "I"]
    responsable: str


class EjemploEntrada(CamelModel):
    model_config = ConfigDict(extra="forbid")
    regla: ReglaEntrada
    id_agencia: Annotated[str, StringConstraints(pattern=r"^[0-9]{3}$")] | None = None


class EjemploVista(CamelModel):
    ejemplo: str | None
    estado_secuencia: Literal["DISPONIBLE", "AGOTADA", "SIN_REGLA", "SIN_AGENCIA"]
    agencia_ejemplo: str | None


class NumeracionVista(EjemploVista):
    regla: ReglaVista | None
    usada: bool
    historial: list[ReglaVista]
    solicitud_pendiente: int | None
