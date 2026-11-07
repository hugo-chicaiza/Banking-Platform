"""DTO de Caja (OpenAPI `CAJ01`..`CAJ18`). camelCase en el JSON, Decimal en Python."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from pydantic import (
    AfterValidator,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)
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


# --- CAJ-12: movimientos de caja ----------


class MovimientoCaja(CamelModel):
    id_movimiento_caja: int
    id_transaccion: int | None = None
    id_jornada_caja: int | None = None
    id_tipo_movimiento: int | None = None
    codigo_tipo_movimiento: str | None = None
    naturaleza: str | None = None
    monto: Money | None = None
    fecha_hora: FechaHoraEc | None = None
    observacion: str | None = None
    id_asiento_contable: int | None = None


class PageMovimientoCaja(CamelModel):
    items: list[MovimientoCaja]
    page: int
    page_size: int
    total: int


# --- CAJ-14: consultar cuadre ----------


class CuadreCaja(CamelModel):
    id_cuadre_caja: int
    id_jornada_caja: int | None = None
    id_usuario: int | None = None
    fecha_hora_cuadre: FechaHoraEc | None = None
    saldo_inicial: Money | None = None
    total_dotaciones: Money | None = None
    total_depositos: Money | None = None
    total_retiros: Money | None = None
    total_pagos: Money | None = None
    total_devoluciones_boveda: Money | None = None
    saldo_esperado: Money | None = None
    saldo_final_fisico: Money | None = None
    diferencia_dinero: Money | None = None
    estado_cuadre: str
    id_autorizado_por: int | None = None
    id_fecha_contable: int | None = None
    observaciones: str | None = None


# --- CAJ-06: cancelación de jornada ----------


class ReversoRequest(Entrada):
    """Motivo de cancelación de jornada o reverso."""

    motivo: Texto500


# --- CAJ-03: apertura de jornada ----------


class JornadaOpen(Entrada):
    id_caja_fisica: IdInt
    dinero_inicial: MontoNoNegativo
    observacion: Texto500 | None = None


# --- CAJ-07: dotación ----------


class Desglose(CamelModel):
    id_denominacion: IdInt
    cantidad: Annotated[int, Field(gt=0, le=100_000)]


DesgloseLista = Annotated[
    list[Desglose],
    Field(min_length=1, max_length=30),
]


def sin_denominaciones_repetidas(
    desglose: list[Desglose] | None,
) -> None:
    if desglose is None:
        return

    ids = [d.id_denominacion for d in desglose]

    if len(ids) != len(set(ids)):
        raise ValueError("El desglose repite una denominación")


class DotacionRequest(Entrada):
    id_boveda: IdInt
    autorizado_por: IdInt
    tipo_dotacion: Literal["INICIAL", "ADICIONAL"]
    desglose: DesgloseLista
    observacion: Texto500 | None = None

    @model_validator(mode="after")
    def _desglose_unico(self) -> "DotacionRequest":
        sin_denominaciones_repetidas(self.desglose)
        return self


# --- CAJ-13: generar cuadre ----------


class CuadreCajaCreate(Entrada):
    observaciones: Texto500 | None = None


# --- CAJ-16: conteo físico ----------


class ConteoFisico(Entrada):
    saldo_final_fisico: MontoNoNegativo
    observaciones: Texto500 | None = None


# --- CAJ-15: devolución a bóveda ----------


class DevolucionRequest(Entrada):
    id_cuadre_caja: IdInt
    id_boveda_destino: IdInt
    autorizado_por: IdInt
    desglose: DesgloseLista
    observacion: Texto500 | None = None

    @model_validator(mode="after")
    def _desglose_unico(self) -> "DevolucionRequest":
        sin_denominaciones_repetidas(self.desglose)
        return self


class Devolucion(CamelModel):
    id_devolucion_caja: int
    id_jornada_caja: int | None = None
    id_cuadre_caja: int | None = None
    id_boveda_destino: int | None = None
    monto: Money | None = None
    id_movimiento_boveda: int | None = None
    supera_limite_maximo: bool | None = None


# --- CAJ-17: autorización del cuadre ----------


class AutorizacionCuadre(Entrada):
    autorizado_por: IdInt
    observaciones: Texto500 | None = None


# --- CAJ-09: depósito en ventanilla ----------


RegistroUnico = Annotated[
    str,
    StringConstraints(
        min_length=12,
        max_length=12,
        pattern=r"^[A-Za-z0-9]{12}$",
    ),
]


class OperacionVentanilla(Entrada):
    """Depósito CAJ-09 y retiro CAJ-11."""

    id_cuenta: IdInt
    monto: MontoPositivo
    registro_unico: RegistroUnico
    desglose: DesgloseLista | None = None
    observacion: (
        Annotated[
            str,
            StringConstraints(
                strip_whitespace=True,
                min_length=1,
                max_length=300,
            ),
        ]
        | None
    ) = None

    @model_validator(mode="after")
    def _desglose_unico(self) -> "OperacionVentanilla":
        sin_denominaciones_repetidas(self.desglose)
        return self


class Comprobante(CamelModel):
    id_transaccion: int
    numero_comprobante: str
    tipo_transaccion: str | None = None
    estado: str
    codigo_respuesta: str
    descripcion_respuesta: str | None = None
    monto: Money | None = None
    comision: Money | None = None
    saldo_disponible: Money | None = None
    denominaciones: list[Desglose] | None = None
    fecha_hora_sistema: FechaHoraEc | None = None
    numero_autorizacion: str | None = None
