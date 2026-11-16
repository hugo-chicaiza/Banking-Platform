"""Contratos de Productos y subproductos (plan E3-02, sobre las tablas que existen).

ProductosFinancieros.Producto: CodigoProducto varchar(10) único, NombreProducto
varchar(100), TipoProducto (CK Cuenta/Credito/Tarjeta), MontoAperturaMinimo >= 0,
IdTipoCredito obligatorio en Credito, IdRed obligatorio en Tarjeta, TipoCuenta
(Ahorro/Corriente) solo en Cuenta, PermiteOperacionesPresenciales, Estado A/I,
Descripcion varchar(250) NULL (migración 20261115). SubProducto: CodigoSubProducto
varchar(15) único, NombreSubProducto varchar(100), Estado A/I.
"""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal, Self

from pydantic import ConfigDict, Field, StringConstraints, model_validator

from app.core.api.schemas import CamelModel, Money
from app.modules.catalogos.schemas import TipoProducto
from app.modules.catalogos.subproductos import TipoTarjeta

INT32_MAX = 2_147_483_647
Estado = Literal["A", "I"]
TipoCuenta = Literal["Ahorro", "Corriente"]
# Sin caracteres de control: termina en pantallas, PDF, reportes y auditoría
_TEXTO = r"^[^\x00-\x1f\x7f]+$"
CodigoProducto = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, to_upper=True, pattern=r"^[A-Z0-9]{3,10}$"
    ),
]
CodigoSubProducto = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, to_upper=True, pattern=r"^[A-Z0-9-]{3,15}$"
    ),
]
Nombre = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=3, max_length=100, pattern=_TEXTO
    ),
]
Descripcion = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=250, pattern=_TEXTO
    ),
]
Monto = Annotated[
    Decimal, Field(ge=0, le=Decimal("9999999999999999.99"), decimal_places=2)
]
IdPositivo = Annotated[int, Field(ge=1, le=INT32_MAX)]


class _Entrada(CamelModel):
    """Campos desconocidos (estado en el POST, código en el PATCH) son 400."""

    model_config = ConfigDict(extra="forbid", validate_by_name=False)


class ProductoCreate(_Entrada):
    """Se crea Inactivo: no se ofrece hasta que el ADMIN lo activa."""

    codigo_producto: CodigoProducto
    nombre_producto: Nombre
    descripcion: Descripcion | None = None
    tipo_producto: TipoProducto
    # Cuenta
    tipo_cuenta: TipoCuenta | None = None
    monto_apertura_minimo: Monto | None = None
    # Credito
    id_tipo_credito: IdPositivo | None = None
    # Tarjeta
    id_red: IdPositivo | None = None
    permite_operaciones_presenciales: bool = True

    @model_validator(mode="after")
    def _por_tipo(self) -> Self:
        propios = {
            "Cuenta": {"tipo_cuenta", "monto_apertura_minimo"},
            "Credito": {"id_tipo_credito"},
            "Tarjeta": {"id_red"},
        }
        ajenos = {
            campo
            for tipo, campos in propios.items()
            if tipo != self.tipo_producto
            for campo in campos
        }
        enviados = {c for c in ajenos if getattr(self, c) is not None}
        if enviados:
            raise ValueError(
                f"Campos que no aplican a un producto {self.tipo_producto}: {', '.join(sorted(enviados))}."
            )
        if self.tipo_producto == "Cuenta" and self.tipo_cuenta is None:
            raise ValueError("tipoCuenta es obligatorio en un producto Cuenta.")
        if self.tipo_producto == "Credito" and self.id_tipo_credito is None:
            raise ValueError("idTipoCredito es obligatorio en un producto Credito.")
        if self.tipo_producto == "Tarjeta" and self.id_red is None:
            raise ValueError("idRed es obligatorio en un producto Tarjeta.")
        return self


class ProductoUpdate(_Entrada):
    """PATCH parcial. El tipo no cambia. El código solo cambia mientras el producto está
    inactivo y sin uso (borrador): activo o usado, 409 PRODUCTO_NO_EDITABLE."""

    codigo_producto: CodigoProducto | None = None
    nombre_producto: Nombre | None = None
    # null borra la descripción
    descripcion: Descripcion | None = None
    monto_apertura_minimo: Monto | None = None
    permite_operaciones_presenciales: bool | None = None
    estado: Estado | None = None

    @model_validator(mode="after")
    def _algo(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("Envíe al menos un campo para actualizar.")
        for campo in (
            "codigo_producto",
            "nombre_producto",
            "monto_apertura_minimo",
            "permite_operaciones_presenciales",
            "estado",
        ):
            if campo in self.model_fields_set and getattr(self, campo) is None:
                raise ValueError(f"{campo} no admite null.")
        return self


# Elegibilidad por edad (años cumplidos); null = sin límite. Menores: edad_maxima = 17
Edad = Annotated[int, Field(ge=0, le=120)]


class SubProductoCreate(_Entrada):
    codigo_sub_producto: CodigoSubProducto
    nombre_sub_producto: Nombre
    edad_minima: Edad | None = None
    edad_maxima: Edad | None = None


class SubProductoUpdate(_Entrada):
    nombre_sub_producto: Nombre | None = None
    estado: Estado | None = None
    # null quita el límite
    edad_minima: Edad | None = None
    edad_maxima: Edad | None = None

    @model_validator(mode="after")
    def _algo(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("Envíe al menos un campo para actualizar.")
        sin_null = {"nombre_sub_producto", "estado"} & self.model_fields_set
        if any(getattr(self, c) is None for c in sin_null):
            raise ValueError("nombreSubProducto y estado no admiten null.")
        return self


MontoLimite = Annotated[
    Decimal, Field(gt=0, le=Decimal("9999999999999999.99"), decimal_places=2)
]


class SubProducto(CamelModel):
    id_sub_producto: int
    id_producto: int
    codigo_sub_producto: str
    nombre_sub_producto: str
    estado: Estado
    fecha_registro: datetime
    tipo_tarjeta: TipoTarjeta | None = None
    edad_minima: int | None = None
    edad_maxima: int | None = None


class Producto(CamelModel):
    id_producto: int
    codigo_producto: str
    nombre_producto: str
    descripcion: str | None = None
    tipo_producto: TipoProducto
    tipo_cuenta: TipoCuenta | None = None
    monto_apertura_minimo: Money | None = None
    id_tipo_credito: int | None = None
    nombre_tipo_credito: str | None = None
    id_red: int | None = None
    nombre_red: str | None = None
    permite_operaciones_presenciales: bool
    estado: Estado
    subproductos: list[SubProducto] = Field(default_factory=list)


# ---------- Cupos por canal (ProductosFinancieros.ProductoCanalCupo) ----------


class CupoCanal(_Entrada):
    """Máximos del subproducto en un canal. Los cupos que el cliente personaliza (CTA-08)
    no pueden superarlos. Mismas reglas que CK_ProductoCanalCupo_*."""

    id_canal: IdPositivo
    cupo_diario_maximo: MontoLimite
    cupo_mensual_maximo: MontoLimite
    monto_max_transaccion: MontoLimite
    # El orden entre cupos (mensual >= diario >= por transacción) lo valida el servicio:
    # 422 CUPOS_INCOHERENTES (E3-03 AC 4)
    max_transacciones_dia: Annotated[int, Field(ge=1, le=10_000)]


class CuposSubProducto(_Entrada):
    """Reemplaza los canales habilitados: el canal que no viene se quita."""

    cupos: Annotated[list[CupoCanal], Field(max_length=20)]

    @model_validator(mode="after")
    def _sin_repetidos(self) -> Self:
        canales = [c.id_canal for c in self.cupos]
        if len(set(canales)) != len(canales):
            raise ValueError("Cada canal va una sola vez.")
        return self


class CupoCanalVista(CamelModel):
    id_canal: int
    codigo_canal: str
    nombre_canal: str
    habilitado: bool
    cupo_diario_maximo: Money | None = None
    cupo_mensual_maximo: Money | None = None
    monto_max_transaccion: Money | None = None
    max_transacciones_dia: int | None = None


# ---------- Restricciones de cuenta (ProductosFinancieros.ProductoRestriccion) ----------


class RestriccionesSubProducto(_Entrada):
    """null = sin esa restricción. SIN_RETIROS en días; SALDO_MINIMO en USD."""

    dias_sin_retiros: Annotated[int, Field(ge=1, le=3650)] | None = None
    saldo_minimo: MontoLimite | None = None


class RestriccionesVista(CamelModel):
    dias_sin_retiros: int | None = None
    saldo_minimo: Money | None = None


# ---------- Vínculos con tasas, comisiones, seguros y amortización ----------

CodigoSistema = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, to_upper=True, pattern=r"^[A-Za-z]{3,10}$"
    ),
]


class ComisionVinculo(_Entrada):
    id_comision: IdPositivo
    # Solo en subproductos: no cobra la comisión que el producto sí cobra
    exonerado: bool = False


class SeguroVinculo(_Entrada):
    id_seguro: IdPositivo
    es_obligatorio: bool = False


class VinculosEntrada(_Entrada):
    """Checklist completo: lo que no viene queda desmarcado (Estado 'I')."""

    tasas_interes: Annotated[list[IdPositivo], Field(max_length=100)] = Field(
        default_factory=list
    )
    comisiones: Annotated[list[ComisionVinculo], Field(max_length=100)] = Field(
        default_factory=list
    )
    seguros: Annotated[list[SeguroVinculo], Field(max_length=50)] = Field(
        default_factory=list
    )
    sistemas_amortizacion: Annotated[list[CodigoSistema], Field(max_length=10)] = Field(
        default_factory=list
    )

    @model_validator(mode="after")
    def _sin_repetidos(self) -> Self:
        listas: list[list[Any]] = [
            self.tasas_interes,
            [c.id_comision for c in self.comisiones],
            [s.id_seguro for s in self.seguros],
            self.sistemas_amortizacion,
        ]
        if any(len(set(lista)) != len(lista) for lista in listas):
            raise ValueError("Las listas no admiten elementos repetidos.")
        return self


class ComisionVinculada(CamelModel):
    id_comision: int
    exonerado: bool


class SeguroVinculado(CamelModel):
    id_seguro: int
    es_obligatorio: bool


class VinculosBase(CamelModel):
    tasas_interes: list[int] = Field(default_factory=list)
    comisiones: list[ComisionVinculada] = Field(default_factory=list)
    seguros: list[SeguroVinculado] = Field(default_factory=list)
    sistemas_amortizacion: list[str] = Field(default_factory=list)


class VinculosVista(VinculosBase):
    # Solo en subproductos: lo que heredan del producto
    del_producto: VinculosBase | None = None


# ---------- Tipos de producto y ficha del subproducto ----------


class TipoProductoInfo(CamelModel):
    """Los tipos vienen con el software: no se crean desde la API (E3-02 AC 2)."""

    codigo: TipoProducto
    nombre: str
    descripcion: str


class TasaFicha(CamelModel):
    id_tasa_interes: int
    tipo_tasa: str
    tasa_nominal_anual: Money
    monto_minimo: Money | None = None
    monto_maximo: Money | None = None
    plazo_maximo_meses: int | None = None
    vigente: bool
    del_producto: bool


class ComisionFicha(CamelModel):
    id_comision: int
    codigo_comision: str
    descripcion: str
    tipo_calculo: str
    valor: Money
    nombre_canal: str
    del_producto: bool


class SeguroFicha(CamelModel):
    id_seguro: int
    nombre: str
    tipo_calculo: str
    valor: Money
    es_obligatorio: bool
    del_producto: bool


class FichaSubProducto(CamelModel):
    """Lo que el asesor lee al cliente: lo vigente hoy del subproducto y lo que hereda."""

    producto: Producto
    subproducto: SubProducto
    cupos: list[CupoCanalVista]
    restricciones: RestriccionesVista | None = None
    tasas: list[TasaFicha]
    # Sin las exoneradas en el subproducto
    comisiones: list[ComisionFicha]
    seguros: list[SeguroFicha]
    sistemas_amortizacion: list[str]
