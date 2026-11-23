"""Catálogo de direcciones: códigos estables y nombres editables."""

from sqlalchemy import Connection, text

from app.core.api.errors import problema
from app.core.api.schemas import CamelModel


class TipoDireccion(CamelModel):
    codigo: str
    nombre: str
    estado: str


def listar(conn: Connection) -> list[TipoDireccion]:
    # Se incluyen inactivos para reconocer los tipos de direcciones ya guardadas.
    filas = conn.execute(
        text(
            "SELECT Codigo, Nombre, Estado FROM Catalogo.TipoDireccion ORDER BY Nombre"
        )
    ).mappings()
    return [
        TipoDireccion(codigo=f["Codigo"], nombre=f["Nombre"], estado=f["Estado"])
        for f in filas
    ]


def validar_activo(conn: Connection, codigo: str) -> None:
    existe = conn.execute(
        text(
            "SELECT Codigo FROM Catalogo.TipoDireccion WHERE Codigo=:codigo AND Estado='A'"
        ),
        {"codigo": codigo},
    ).scalar()
    if existe != codigo:
        raise problema(
            422,
            "TIPO_DIRECCION_INVALIDO",
            "Selecciona un tipo de dirección activo del catálogo.",
        )
