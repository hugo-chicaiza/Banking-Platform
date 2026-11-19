"""Contratos E1-12. El actor y los identificadores de auditoría son del servidor."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import ConfigDict, Field, model_validator

from app.core.api.schemas import CamelModel, Money

Id = Annotated[int, Field(strict=True, ge=1, le=2_147_483_647)]
Importe = Annotated[Decimal, Field(ge=0, max_digits=18, decimal_places=2)]
Valor = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=4)]
Porcentaje = Annotated[Decimal, Field(ge=0, le=100, decimal_places=2)]
Estado = Literal["A", "I"]
TipoComision = Literal[
    "Retiro",
    "Transferencia",
    "Consulta",
    "Mantenimiento",
    "Emision Tarjeta",
    "Reposicion Tarjeta",
    "Otro",
]


class Entrada(CamelModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Vigencia(Entrada):
    vigencia_desde: date
    vigencia_hasta: date | None = None

    @model_validator(mode="after")
    def intervalo(self) -> Self:
        if (
            self.vigencia_hasta is not None
            and self.vigencia_hasta <= self.vigencia_desde
        ):
            raise ValueError("La vigencia hasta debe ser posterior al inicio")
        return self


class AsociarComision(Vigencia):
    id_comision: Id
    id_canal: Id
    codigo_tipo_transaccion: str = Field(min_length=1, max_length=30)


class ComisionCreate(Vigencia):
    codigo_comision: str = Field(
        min_length=2, max_length=10, pattern=r"^[A-Za-z0-9_-]+$"
    )
    tipo_comision: TipoComision
    tipo_calculo: Literal["Fijo", "Porcentaje"]
    valor: Valor
    monto_minimo: Importe | None = None
    monto_maximo: Importe | None = None
    id_canal: Id
    codigo_tipo_transaccion: str = Field(min_length=1, max_length=30)
    descripcion: str = Field(min_length=1, max_length=250)
    id_cuenta_contable_ingreso: Id | None = None

    @model_validator(mode="after")
    def calculo(self) -> Self:
        if self.tipo_calculo == "Fijo" and (
            self.monto_minimo is not None or self.monto_maximo is not None
        ):
            raise ValueError("Una comisión fija no admite límites porcentuales")
        if self.tipo_calculo == "Porcentaje" and (
            self.valor > 100 or self.monto_minimo is None or self.monto_maximo is None
        ):
            raise ValueError(
                "Una comisión porcentual exige valor 0–100 y ambos límites"
            )
        if (
            self.monto_minimo is not None
            and self.monto_maximo is not None
            and self.monto_minimo > self.monto_maximo
        ):
            raise ValueError("El mínimo no puede exceder al máximo")
        return self


class ComisionUpdate(Entrada):
    descripcion: str | None = Field(default=None, min_length=1, max_length=250)
    estado: Estado | None = None
    id_cuenta_contable_ingreso: Id | None = None
    valor: Valor | None = None
    vigencia_desde: date | None = None

    @model_validator(mode="after")
    def campos(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("Debe enviar al menos un cambio")
        if any(
            getattr(self, k) is None
            for k in self.model_fields_set - {"id_cuenta_contable_ingreso"}
        ):
            raise ValueError("El campo enviado no admite null")
        return self


class ExoneracionCreate(Vigencia):
    id_comision: Id
    id_producto: Id | None = None
    id_sub_producto: Id | None = None
    tipo_cliente: Literal["Natural", "Juridico"] | None = None
    operaciones_gratis_mes: (
        Annotated[int, Field(strict=True, ge=0, le=32767)] | None
    ) = None
    porcentaje_exonerado: Porcentaje
    estado: Estado = "A"


class TarifaVigente(CamelModel):
    id_comision: int
    valor: Valor
    vigencia_desde: date
    vigencia_hasta: date | None


class ExoneracionUpdate(Entrada):
    id_producto: Id | None = None
    id_sub_producto: Id | None = None
    tipo_cliente: Literal["Natural", "Juridico"] | None = None
    operaciones_gratis_mes: (
        Annotated[int, Field(strict=True, ge=0, le=32767)] | None
    ) = None
    porcentaje_exonerado: Porcentaje | None = None
    vigencia_desde: date | None = None
    vigencia_hasta: date | None = None
    estado: Estado | None = None

    @model_validator(mode="after")
    def campos(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("Debe enviar al menos un cambio")
        for k in self.model_fields_set & {
            "porcentaje_exonerado",
            "vigencia_desde",
            "estado",
        }:
            if getattr(self, k) is None:
                raise ValueError("El campo enviado no admite null")
        return self


class Asociacion(CamelModel):
    id_comision_tipo_transaccion: int
    codigo_tipo_transaccion: str
    vigencia_desde: date
    vigencia_hasta: date | None
    estado: Estado
    registrado_por: int


class Comision(CamelModel):
    id_comision: int
    codigo_comision: str
    tipo_comision: str
    tipo_calculo: str
    valor: Money
    monto_minimo: Money | None
    monto_maximo: Money | None
    id_canal: int
    descripcion: str
    vigencia_desde: date
    vigencia_hasta: date | None
    estado: Estado
    id_cuenta_contable_ingreso: int | None
    asociaciones: list[Asociacion] = Field(default_factory=list)


class Exoneracion(ExoneracionCreate):
    id_exoneracion: int
    creado_por: int | None
    fecha_creacion: datetime


class CobroComision(CamelModel):
    id_comision: int
    monto_base: Money
    monto_cobrar: Money
    id_exoneracion: int | None
