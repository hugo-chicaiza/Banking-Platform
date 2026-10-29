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
