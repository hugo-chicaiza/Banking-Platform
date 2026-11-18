"""SQL parametrizado de Seguridad.PestanaRol (SeguridadDB)."""

from sqlalchemy import Connection, text


def pestanas(conn: Connection) -> list[tuple[str, str]]:
    """(Pestana, Roles separados por coma) de las pestañas configuradas."""
    filas = conn.execute(
        text("SELECT Pestana, Roles FROM Seguridad.PestanaRol ORDER BY Pestana")
    )
    return [(str(p), str(r)) for p, r in filas]


def reemplazar_pestanas(
    conn: Connection, filas: list[tuple[str, str]], usuario: int
) -> None:
    """Reemplaza toda la configuración (dentro de la transacción del llamador)."""
    conn.execute(text("DELETE FROM Seguridad.PestanaRol"))
    for pestana, roles in filas:
        conn.execute(
            text(
                "INSERT INTO Seguridad.PestanaRol (Pestana, Roles, ModificadoPor) "
                "VALUES (:pestana, :roles, :usuario)"
            ),
            {"pestana": pestana, "roles": roles, "usuario": usuario},
        )
