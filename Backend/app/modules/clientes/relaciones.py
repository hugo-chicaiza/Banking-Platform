"""Lectura de vínculos que habilitan a un tercero a actuar por el titular."""

from datetime import date
from typing import Literal

from sqlalchemy import Connection, text

from app.core.api.errors import problema
from app.modules.parametros import general

RolRelacion = Literal["Tutor", "RepresentanteLegal"]


def edad_en(nacimiento: date, fecha: date) -> int:
    return (
        fecha.year
        - nacimiento.year
        - ((fecha.month, fecha.day) < (nacimiento.month, nacimiento.day))
    )


def edad_mayoria(conn: Connection, fecha: date) -> int:
    edad = general.valor(conn, "CLI_EDAD_MAYORIA", fecha)
    if type(edad) is not int or edad < 1:
        raise problema(
            503, "PARAMETRO_INVALIDO", "No se pudo verificar la mayoría de edad."
        )
    return edad


def relacion_vigente(
    conn: Connection, id_cliente: int, tipo: RolRelacion, fecha: date
) -> dict | None:
    filas = (
        conn.execute(
            text("""
            SELECT TOP (2) r.IdRelacion, r.IdClienteRelacionado, r.FechaFin, r.IdArchivoSoporte,
                   c.FechaNacimiento
            FROM Clientes.ClienteRelacion AS r WITH (HOLDLOCK)
            JOIN Catalogo.TipoRelacionCliente AS t WITH (HOLDLOCK)
              ON t.Codigo=r.TipoRelacion AND t.Estado='A'
            JOIN Clientes.Cliente AS c WITH (HOLDLOCK)
              ON c.IdCliente=r.IdClienteRelacionado AND c.Estado='Activo' AND c.TipoCliente='Natural'
            WHERE r.IdCliente=:id AND r.TipoRelacion=:tipo
              AND r.FechaInicio<=:fecha AND (r.FechaFin IS NULL OR r.FechaFin>=:fecha)
            ORDER BY r.FechaInicio DESC, r.IdRelacion DESC
        """),
            {"id": id_cliente, "tipo": tipo, "fecha": fecha},
        )
        .mappings()
        .all()
    )
    if len(filas) > 1:
        raise problema(
            409,
            "RELACION_AMBIGUA",
            "Hay más de una relación vigente para el mismo rol.",
        )
    if not filas or filas[0]["FechaNacimiento"] is None:
        return None
    fila = filas[0]
    return (
        dict(fila)
        if edad_en(fila["FechaNacimiento"], fecha) >= edad_mayoria(conn, fecha)
        else None
    )
