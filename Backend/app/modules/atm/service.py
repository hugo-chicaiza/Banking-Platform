from sqlalchemy import Connection

from app.core.api.errors import problema
from app.modules.atm import repository


def validar_terminal(
    conn: Connection,
    codigo_atm: str,
) -> dict:
    """Valida que el terminal ATM pueda operar."""

    atm = repository.obtener_atm(conn, codigo_atm)

    if atm is None:
        raise problema(
            409,
            "ATM_FUERA_DE_SERVICIO",
            "El cajero no está disponible.",
        )

    if atm["tipo_terminal"] != "ATM":
        raise problema(
            409,
            "ATM_FUERA_DE_SERVICIO",
            "El cajero no está disponible.",
        )

    if atm["estado_atm"] != "A":
        raise problema(
            409,
            "ATM_FUERA_DE_SERVICIO",
            "El cajero no está disponible.",
        )

    if atm["estado_canal"] != "A":
        raise problema(
            409,
            "ATM_FUERA_DE_SERVICIO",
            "El cajero no está disponible.",
        )

    if not all(
        (
            atm["requiere_tarjeta"],
            atm["requiere_pin"],
            atm["requiere_terminal"],
        )
    ):
        raise problema(
            409,
            "ATM_FUERA_DE_SERVICIO",
            "El cajero no está disponible.",
        )

    return atm
