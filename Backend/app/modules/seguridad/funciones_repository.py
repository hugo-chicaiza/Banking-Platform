"""Persistencia de ajustes; la transacción y el bloqueo pertenecen al servicio."""

from sqlalchemy import Connection, text

Ajustes = dict[tuple[str, str], bool]


def leer(conn: Connection) -> Ajustes:
    filas = conn.execute(
        text("SELECT Funcion, Rol, Permitido FROM Seguridad.AccesoFuncionRol")
    )
    return {(fila[0], fila[1]): bool(fila[2]) for fila in filas}


def escribir(
    conn: Connection, funcion: str, rol: str, permitido: bool | None, actor: int
) -> None:
    valores = {"funcion": funcion, "rol": rol, "permitido": permitido, "actor": actor}
    conn.execute(
        text(
            "DELETE FROM Seguridad.AccesoFuncionRol WHERE Funcion=:funcion AND Rol=:rol"
        ),
        valores,
    )
    if permitido is not None:
        conn.execute(
            text("""
            INSERT INTO Seguridad.AccesoFuncionRol
                (Funcion, Rol, Permitido, ModificadoPor, FechaModificacion)
            VALUES (:funcion, :rol, :permitido, :actor, SYSUTCDATETIME())
        """),
            valores,
        )
