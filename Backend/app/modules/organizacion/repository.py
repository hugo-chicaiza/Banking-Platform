from typing import Any

from sqlalchemy import Connection, text


def bloquear_agencia(conn: Connection, id_agencia: str) -> dict[str, Any] | None:
    fila = (
        conn.execute(
            text("""
            SELECT IdAgencia AS id_agencia, Estado AS estado
            FROM Organizacion.Agencia WITH (UPDLOCK, HOLDLOCK)
            WHERE IdAgencia = :id
        """),
            {"id": id_agencia},
        )
        .mappings()
        .one_or_none()
    )
    return dict(fila) if fila is not None else None


def actualizar_estado(
    conn: Connection, id_agencia: str, anterior: str, nuevo: str
) -> bool:
    resultado = conn.execute(
        text("""
            UPDATE Organizacion.Agencia SET Estado = :nuevo
            WHERE IdAgencia = :id AND Estado = :anterior
        """),
        {"id": id_agencia, "anterior": anterior, "nuevo": nuevo},
    )
    return resultado.rowcount == 1
