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
from typing import Annotated, Literal, Self

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
    """PATCH parcial. Código y tipo no cambian: los usan cuentas, tarjetas y créditos."""

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
            "nombre_producto",
            "monto_apertura_minimo",
            "permite_operaciones_presenciales",
            "estado",
        ):
            if campo in self.model_fields_set and getattr(self, campo) is None:
                raise ValueError(f"{campo} no admite null.")
        return self


class SubProductoCreate(_Entrada):
    codigo_sub_producto: CodigoSubProducto
    nombre_sub_producto: Nombre


class SubProductoUpdate(_Entrada):
    nombre_sub_producto: Nombre | None = None
    estado: Estado | None = None

    @model_validator(mode="after")
    def _algo(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("Envíe al menos un campo para actualizar.")
        if any(getattr(self, c) is None for c in self.model_fields_set):
            raise ValueError("Los campos enviados no admiten null.")
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
    max_transacciones_dia: Annotated[int, Field(ge=1, le=10_000)]

    @model_validator(mode="after")
    def _coherentes(self) -> Self:
        if self.cupo_mensual_maximo < self.cupo_diario_maximo:
            raise ValueError("El cupo mensual debe ser mayor o igual que el diario.")
        if self.monto_max_transaccion > self.cupo_diario_maximo:
            raise ValueError(
                "El monto por transacción no puede superar el cupo diario."
            )
        return self


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
