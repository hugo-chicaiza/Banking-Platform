"""SQL ligado; no confirma transacciones ni autentica identidades."""

import re
from typing import Any

from sqlalchemy import Connection, text

from app.core.api.errors import problema


def consulta(sql: str):
    for nombre, tipo in {
        "agencia": "char(3)",
        "comentario": "nvarchar(300)",
        "nombre": "nvarchar(150)",
        "interno": "int",
        "anterior": "varchar(12)",
        "error": "varchar(60)",
    }.items():
        sql = re.sub(
            r":" + nombre + r"\b", "CAST(:" + nombre + " AS " + tipo + ")", sql
        )
    return text(sql)


def obtener(
    conn: Connection, id_: int, organizacion: str, bloquear: bool = False
) -> dict[str, Any]:
    sql = (
        "SELECT * FROM Seguridad.SolicitudAprobacion WITH(UPDLOCK,HOLDLOCK) WHERE IdSolicitud=:id AND IdOrganizacion=:org"
        if bloquear
        else "SELECT * FROM Seguridad.SolicitudAprobacion WHERE IdSolicitud=:id AND IdOrganizacion=:org"
    )
    fila = (
        conn.execute(consulta(sql), {"id": id_, "org": organizacion}).mappings().first()
    )
    if fila is None:
        raise problema(404, "SOLICITUD_NO_ENCONTRADA", "La solicitud no existe.")
    return dict(fila)


def pendiente(fila: dict[str, Any]) -> None:
    if fila["Estado"] != "Pendiente":
        raise problema(409, "SOLICITUD_NO_PENDIENTE", "La solicitud ya fue resuelta.")


def evento(
    conn: Connection,
    id_: int,
    anterior: str | None,
    nuevo: str,
    sujeto: str | None,
    nombre: str | None,
    interno: int | None,
    comentario: str | None = None,
) -> None:
    conn.execute(
        consulta("""INSERT Seguridad.SolicitudAprobacionEvento
        (IdSolicitud,EstadoAnterior,EstadoNuevo,Sujeto,Nombre,IdInterno,Comentario)
        VALUES(:id,:anterior,:nuevo,:sujeto,:nombre,:interno,:comentario)"""),
        {
            "id": id_,
            "anterior": anterior,
            "nuevo": nuevo,
            "sujeto": sujeto,
            "nombre": nombre,
            "interno": interno,
            "comentario": comentario,
        },
    )
