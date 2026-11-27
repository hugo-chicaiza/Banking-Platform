"""Contrato BOV01..BOV06: dinero decimal y fechas con hora de Ecuador."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from app.core.api.schemas import CamelModel, Money
from app.modules.contabilidad.service import ZONA_ECUADOR

INT32_MAX = 2_147_483_647
INT64_MAX = 9_223_372_036_854_775_807
IdInt = Annotated[int, Field(strict=True, gt=0, le=INT32_MAX)]
Cantidad = Annotated[int, Field(strict=True, ge=0, le=INT32_MAX)]
TipoBoveda = Literal["General", "Mayor", "Menor"]
TipoArqueo = Literal["Sorpresivo", "Programado"]
EstadoArqueo = Literal[
    "REGISTRADO", "APROBADO", "ANULADO", "CUADRADO", "FALTANTE", "SOBRANTE"
]
TipoResolucionNovedad = Literal["JUSTIFICACION", "REPOSICION", "DESCUENTO_ROL"]
TipoOperacion = Literal[
    "Traslado", "ProvisionExterna", "EnvioExcedente", "AjusteFaltante", "AjusteSobrante"
]
TipoMovimiento = Literal[
    "Traslado",
    "ProvisionExterna",
    "EnvioExcedente",
    "RetornoRemesa",
    "AjusteFaltante",
    "AjusteSobrante",
    "DotacionCaja",
    "DevolucionCaja",
    "AbastecimientoATM",
    "RemanenteATM",
    "ReposicionFaltante",
]


def _fecha_ec(valor: datetime) -> datetime:
    return (
        valor.replace(tzinfo=ZONA_ECUADOR)
        if valor.tzinfo is None
        else valor.astimezone(ZONA_ECUADOR)
    )


FechaEc = Annotated[datetime, AfterValidator(_fecha_ec)]


class DenominacionBoveda(CamelModel):
    id_denominacion: int
    cantidad_actual: int
    valor: Money
    subtotal: Money


class Boveda(CamelModel):
    id_boveda: int
    codigo_boveda: str
    tipo_boveda: TipoBoveda
    id_agencia: str
    id_boveda_superior: int | None
    limite_maximo: Money
    limite_minimo: Money
    saldo_actual: Money
    estado: Literal["A", "I"]
    denominaciones: list[DenominacionBoveda]
    total_desglose: Money


class Desglose(CamelModel):
    model_config = ConfigDict(extra="forbid")
    id_denominacion: IdInt
    cantidad: Cantidad


class EntradaDesglose(CamelModel):
    model_config = ConfigDict(extra="forbid")
    desglose: Annotated[list[Desglose], Field(min_length=1, max_length=100)]

    @model_validator(mode="after")
    def sin_duplicados(self):
        ids = [d.id_denominacion for d in self.desglose]
        if len(ids) != len(set(ids)):
            raise ValueError("El desglose repite una denominación.")
        return self


class MovimientoBovedaRequest(EntradaDesglose):
    tipo_movimiento: TipoOperacion
    id_boveda_contraparte: IdInt | None = None
    autorizado_por: IdInt
    observaciones: Annotated[str, Field(max_length=300)] | None = None

    @model_validator(mode="after")
    def cantidades_positivas(self):
        if any(d.cantidad == 0 for d in self.desglose):
            raise ValueError("Las cantidades del movimiento deben ser positivas.")
        return self


class MovimientoBoveda(CamelModel):
    id_movimiento: int
    id_boveda: int
    id_boveda_contraparte: int | None
    tipo_movimiento: TipoMovimiento
    naturaleza: Literal["I", "E"]
    monto: Money
    saldo_anterior: Money
    saldo_posterior: Money
    autorizado_por: int
    id_usuario_movimiento: int
    id_movimiento_relacionado: int | None
    fecha_movimiento: FechaEc
    observaciones: str | None = None
    id_asiento_contable: int | None = None
    id_solicitud_movimiento: int | None = None
    desglose: list[Desglose]


class PageMovimientoBoveda(CamelModel):
    items: list[MovimientoBoveda]
    page: int
    page_size: int
    total: int


class ArqueoBovedaRequest(EntradaDesglose):
    tipo_arqueo: TipoArqueo
    desglose: Annotated[list[Desglose], Field(max_length=100)]
    id_usuario_responsable: IdInt | None = None
    observaciones: Annotated[str, Field(max_length=500)] | None = None


class ResolucionNovedadRequest(EntradaDesglose):
    tipo_resolucion: TipoResolucionNovedad
    observaciones: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)
    ]
    referencia_resolucion: (
        Annotated[
            str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)
        ]
        | None
    ) = None
    desglose: Annotated[list[Desglose], Field(max_length=100)] = Field(
        default_factory=list
    )

    @model_validator(mode="after")
    def validar_resolucion(self):
        if self.tipo_resolucion == "REPOSICION":
            if not self.desglose or any(d.cantidad == 0 for d in self.desglose):
                raise ValueError(
                    "La reposición requiere denominaciones con cantidades positivas."
                )
        elif self.desglose or self.referencia_resolucion is None:
            raise ValueError(
                "La resolución requiere una referencia documental y ningún efectivo."
            )
        return self


class NovedadCajero(CamelModel):
    id_novedad: int
    id_usuario_responsable: int
    monto: Money
    fecha_vencimiento: FechaEc
    estado: Literal["PENDIENTE", "VENCIDA", "RESUELTA"]
    id_asiento_contable: int
    tipo_resolucion: TipoResolucionNovedad | None
    fecha_resolucion: FechaEc | None
    id_usuario_resolucion: int | None
    referencia_resolucion: str | None
    observaciones_resolucion: str | None
    id_asiento_resolucion: int | None
    id_movimiento_reposicion: int | None


class DiferenciaDenominacion(CamelModel):
    id_denominacion: int
    cantidad: int  # Contada menos esperada; puede ser negativa.


class ArqueoBoveda(CamelModel):
    id_arqueo_boveda: int
    id_boveda: int
    fecha_hora_arqueo: FechaEc
    tipo_arqueo: TipoArqueo
    id_usuario_arqueador: int
    id_usuario_testigo: int | None
    estado: EstadoArqueo
    id_movimiento_ajuste: int | None
    ids_movimientos_ajuste: list[int] = Field(default_factory=list)
    diferencia_por_denominacion: list[DiferenciaDenominacion]
    observaciones: str | None
    saldo_teorico: Money
    saldo_fisico: Money
    diferencia: Money
    id_usuario_aprobador: int | None = None
    fecha_hora_aprobacion: FechaEc | None = None
    novedad: NovedadCajero | None = None


class ResumenArqueoBoveda(CamelModel):
    """Cabecera histórica: los arqueos antiguos pueden carecer de referencia."""

    id_arqueo_boveda: int
    id_boveda: int
    fecha_hora_arqueo: FechaEc
    tipo_arqueo: TipoArqueo
    id_usuario_arqueador: int
    id_usuario_testigo: int | None
    estado: EstadoArqueo
    observaciones: str | None
    saldo_teorico: Money | None
    saldo_fisico: Money | None
    diferencia: Money | None
    id_movimiento_ajuste: int | None
    ids_movimientos_ajuste: list[int]
    id_usuario_aprobador: int | None
    fecha_hora_aprobacion: FechaEc | None
    novedad: NovedadCajero | None = None


class PageArqueoBoveda(CamelModel):
    items: list[ResumenArqueoBoveda]
    page: int
    page_size: int
    total: int
