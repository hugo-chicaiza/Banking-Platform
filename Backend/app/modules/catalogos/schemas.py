from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, model_validator

from app.core.api.schemas import CamelModel, Money
from app.modules.catalogos.subproductos import TipoTarjeta


class Pais(CamelModel):
    codigo_pais: str
    codigo_numerico: str
    nombre_pais: str


class Denominacion(CamelModel):
    id_denominacion: int
    tipo_pieza: Literal["Billete", "Moneda"]
    valor: Money
    descripcion: str


class TipoMovimientoCaja(CamelModel):
    id_tipo_movimiento_caja: int
    codigo: str
    descripcion: str
    naturaleza: Literal["I", "E"]


class Canal(CamelModel):
    id_canal: int
    codigo_canal: str
    nombre_canal: str
    requiere_tarjeta: bool
    requiere_pin: bool
    requiere_terminal: bool
    requiere_jornada_caja: bool
    modo: Literal["Digital", "Presencial", "Ambos"]


class ActividadEconomica(CamelModel):
    id_actividad_economica: int
    descripcion: str
    area_actividad: str


class TipoAntecedente(CamelModel):
    id_tipo_antecedente: int
    nombre: str
    categoria: Literal["EnRevision", "Critico"]
    puede_impedir_vinculacion: bool


TipoProducto = Literal["Cuenta", "Tarjeta", "Credito"]


class SubProducto(CamelModel):
    """Variante que el asesor ofrece del producto (p. ej. Débito o Crédito Mastercard)."""

    id_sub_producto: int
    codigo_sub_producto: str
    nombre_sub_producto: str
    # Solo en subproductos de tarjeta (por el prefijo del código, ver subproductos.py)
    tipo_tarjeta: TipoTarjeta | None = None


class Producto(CamelModel):
    id_producto: int
    codigo_producto: str
    nombre_producto: str
    descripcion: str | None = None
    tipo_producto: TipoProducto
    monto_apertura_minimo: Money | None = None
    id_tipo_credito: int | None = None
    id_red: int | None = None
    tipo_cuenta: str | None = None
    permite_operaciones_presenciales: bool
    subproductos: list[SubProducto] = Field(default_factory=list)


class SistemaAmortizacion(CamelModel):
    codigo: str
    nombre: str
    descripcion: str


TipoTasa = Literal[
    "CREDITO",
    "AHORRO",
    "TARJETA_COMPRA",
    "TARJETA_AVANCE",
    "TARJETA_DIFERIDO",
    "TARJETA_EXTERIOR",
    "TARJETA_MORA",
]


class TasaInteres(CamelModel):
    """Tasa con rango de monto y vigencia. CREDITO lleva tipo de crédito y plazo máximo;
    AHORRO y TARJETA_* no tienen tipo de crédito (CK_TasaInteres_TipoCredito)."""

    id_tasa_interes: int
    tipo_tasa: TipoTasa
    id_tipo_credito: int | None = None
    nombre_tipo_credito: str | None = None
    # Fracción anual: 0.16 = 16 %
    tasa_nominal_anual: Money
    recargo_mora_sobre_tasa: Money
    plazo_maximo_meses: int | None = None
    monto_minimo: Money | None = None
    monto_maximo: Money | None = None
    vigencia_desde: date
    vigencia_hasta: date | None = None
    vigente: bool


class TasaInteresCreate(CamelModel):
    """Una tasa CREDITO no puede solaparse con otra del mismo tipo de crédito en monto y
    vigencia: la evaluación exige una sola tasa por consulta (DB 55103). Las de ahorro y
    tarjeta sí pueden coexistir: cada producto vincula la suya."""

    model_config = ConfigDict(extra="forbid", validate_by_name=False)

    tipo_tasa: TipoTasa = "CREDITO"
    id_tipo_credito: Annotated[int, Field(ge=1, le=2_147_483_647)] | None = None
    tasa_nominal_anual: Annotated[Decimal, Field(gt=0, le=1, decimal_places=4)]
    recargo_mora_sobre_tasa: Annotated[Decimal, Field(ge=0, le=1, decimal_places=4)] = (
        Decimal(0)
    )
    plazo_maximo_meses: Annotated[int, Field(ge=1, le=600)] | None = None
    monto_minimo: Annotated[Decimal, Field(gt=0, decimal_places=2)] | None = None
    monto_maximo: Annotated[Decimal, Field(gt=0, decimal_places=2)] | None = None
    vigencia_desde: date
    vigencia_hasta: date | None = None

    @model_validator(mode="after")
    def _rangos(self) -> "TasaInteresCreate":
        if (
            self.monto_minimo
            and self.monto_maximo
            and self.monto_maximo < self.monto_minimo
        ):
            raise ValueError("montoMaximo debe ser mayor o igual que montoMinimo.")
        if self.vigencia_hasta and self.vigencia_hasta <= self.vigencia_desde:
            raise ValueError("vigenciaHasta debe ser posterior a vigenciaDesde.")
        if self.tipo_tasa == "CREDITO":
            if self.id_tipo_credito is None or self.plazo_maximo_meses is None:
                raise ValueError(
                    "Una tasa de crédito necesita tipo de crédito y plazo máximo."
                )
        elif self.id_tipo_credito is not None:
            raise ValueError("Solo las tasas de crédito llevan tipo de crédito.")
        return self


class Comision(CamelModel):
    """Comisión o recargo (Transacciones.Comisiones). Porcentaje: Valor en % (0 a 100)."""

    id_comision: int
    codigo_comision: str
    tipo_comision: str
    tipo_calculo: Literal["Fijo", "Porcentaje"]
    valor: Money
    nombre_canal: str
    descripcion: str


class Seguro(CamelModel):
    id_seguro: int
    codigo_seguro: str
    nombre: str
    aseguradora: str | None = None
    tipo_calculo: Literal["Fijo", "Porcentaje"]
    valor: Money


class Red(CamelModel):
    id_red: int
    codigo_red: str
    nombre: str


class Agencia(CamelModel):
    id_agencia: str
    codigo: str
    nombre: str
    tipo_agencia: Literal["Sucursal", "Matriz"]
    provincia: str
    ciudad: str
    estado: Literal["A", "I", "C"]


class TipoCredito(CamelModel):
    id_tipo_credito: int
    codigo_tipo_credito: str
    nombre: str
    descripcion: str | None = None


class Ciudad(CamelModel):
    id_ciudad: int
    codigo_pais: str
    nombre: str
    provincia: str
