from typing import Literal

from app.core.schemas import CamelModel, Money


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


class Producto(CamelModel):
    id_producto: int
    codigo_producto: str
    nombre_producto: str
    tipo_producto: TipoProducto
    monto_apertura_minimo: Money | None = None
    id_tipo_credito: int | None = None
    id_red: int | None = None
    tipo_cuenta: str | None = None
    permite_operaciones_presenciales: bool


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
