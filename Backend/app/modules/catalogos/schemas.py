from typing import Literal, get_args

from app.core.schemas import CamelModel, Money

TipoProducto = Literal["Cuenta", "Tarjeta", "Credito"]
TIPOS_PRODUCTO = get_args(TipoProducto)


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


class Agencia(CamelModel):
    id_agencia: str
    codigo: str
    nombre: str
    tipo_agencia: Literal["Sucursal", "Matriz"]
    provincia: str
    ciudad: str
    estado: Literal["A", "I", "C"]


class Producto(CamelModel):
    id_producto: int
    codigo_producto: str
    nombre_producto: str
    tipo_producto: TipoProducto
    monto_apertura_minimo: Money | None
    id_tipo_credito: int | None
    id_red: int | None
    tipo_cuenta: str | None
    permite_operaciones_presenciales: bool


class ProblemError(CamelModel):
    field: str
    message: str


class ProblemDetails(CamelModel):
    type: str
    title: str
    status: int
    code: str
    detail: str
    trace_id: str
    errors: list[ProblemError]
