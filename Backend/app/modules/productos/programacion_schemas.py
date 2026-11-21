"""Contratos E3-03: valores nuevos, nunca edicion directa de conjuntos vigentes."""

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import ConfigDict, Field, StringConstraints, model_validator

from app.core.api.schemas import CamelModel
from app.modules.productos.schemas import CupoCanal

Monto = Annotated[Decimal, Field(ge=0, max_digits=18, decimal_places=2)]
Clase = Literal["condiciones", "cupos", "restricciones"]
TipoRestriccion = Literal[
    "SIN_RETIROS",
    "SIN_RETIROS_DIAS",
    "SALDO_MINIMO",
    "SALDO_MAXIMO",
    "MAXIMO_CUENTAS_CLIENTE",
    "SIN_TRANSFERENCIAS_SALIDA",
]


class Entrada(CamelModel):
    model_config = ConfigDict(extra="forbid")


class Fechas(Entrada):
    vigencia_desde: date
    vigencia_hasta: date | None = None

    @model_validator(mode="after")
    def intervalo(self) -> Self:
        if (
            self.vigencia_hasta is not None
            and self.vigencia_hasta < self.vigencia_desde
        ):
            raise ValueError("El fin no puede ser anterior al inicio.")
        return self


class CondicionNueva(Fechas):
    monto_apertura_minimo: Monto
    saldo_minimo: Monto
    tasa_interes_anual: Annotated[
        Decimal, Field(ge=0, le=100, max_digits=7, decimal_places=4)
    ] = Decimal(0)
    periodicidad_interes: (
        Annotated[
            str, StringConstraints(strip_whitespace=True, min_length=1, max_length=12)
        ]
        | None
    ) = None
    costo_mantenimiento: Monto = Decimal(0)
    periodicidad_costo: (
        Annotated[
            str, StringConstraints(strip_whitespace=True, min_length=1, max_length=12)
        ]
        | None
    ) = None
    meses_inactividad: Annotated[int, Field(strict=True, ge=1, le=32767)] | None = None
    aplica_a_cuentas_existentes: bool = False

    @model_validator(mode="after")
    def montos(self) -> Self:
        if self.saldo_minimo > self.monto_apertura_minimo:
            raise ValueError("El saldo minimo no puede superar el monto de apertura.")
        return self


class CuposNuevos(Fechas):
    cupos: Annotated[list[CupoCanal], Field(max_length=20)]

    @model_validator(mode="after")
    def canales_unicos(self) -> Self:
        if len({c.id_canal for c in self.cupos}) != len(self.cupos):
            raise ValueError("Cada canal debe aparecer una sola vez.")
        return self


class RestriccionNueva(Fechas):
    tipo_restriccion: TipoRestriccion
    dias: Annotated[int, Field(strict=True, ge=1, le=32767)] | None = None
    monto: Monto | None = None
    cantidad: Annotated[int, Field(strict=True, ge=1, le=32767)] | None = None
    descripcion: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=250)
    ]


class FinRestriccion(Entrada):
    vigencia_hasta: date


class Cambio(Entrada):
    clase: Clase
    accion: Literal["programar", "cancelar", "fin"]
    datos: dict = Field(default_factory=dict)
    id_registro: Annotated[int, Field(strict=True, gt=0)] | None = None
    id_programacion: Annotated[int, Field(strict=True, gt=0)] | None = None
