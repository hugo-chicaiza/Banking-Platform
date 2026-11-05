from datetime import date, datetime
from typing import Any

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


def validar_tarjeta(
    conn: Connection,
    id_tarjeta: int,
) -> dict[str, Any]:
    """Valida el estado y la vigencia de una tarjeta."""

    tarjeta = repository.obtener_tarjeta(conn, id_tarjeta)

    if tarjeta is None:
        raise problema(
            409,
            "TARJETA_NO_DISPONIBLE",
            "La tarjeta no está disponible.",
        )

    if tarjeta["estado_tarjeta"] != "Activa":
        raise problema(
            409,
            "TARJETA_NO_DISPONIBLE",
            "La tarjeta no está disponible.",
        )

    fecha_expiracion = tarjeta["fecha_expiracion"]

    if isinstance(fecha_expiracion, datetime):
        fecha_expiracion = fecha_expiracion.date()

    if fecha_expiracion is None or fecha_expiracion < date.today():
        raise problema(
            409,
            "TARJETA_NO_DISPONIBLE",
            "La tarjeta no está disponible.",
        )

    if not tarjeta["pin_asignado"]:
        raise problema(
            409,
            "PIN_NO_CONFIGURADO",
            "La tarjeta no tiene un PIN configurado.",
        )

    return tarjeta


def validar_estado_pin(
    conn_seguridad: Connection,
    id_tarjeta: int,
) -> dict[str, Any]:
    """Valida que el PIN esté asignado y habilitado."""

    estado_pin = repository.obtener_estado_pin(
        conn_seguridad,
        id_tarjeta,
    )

    if estado_pin is None:
        raise problema(
            409,
            "PIN_NO_DISPONIBLE",
            "No se puede utilizar el PIN de esta tarjeta.",
        )

    if not estado_pin["tiene_pin_asignado"]:
        raise problema(
            409,
            "PIN_NO_CONFIGURADO",
            "La tarjeta no tiene un PIN configurado.",
        )

    if estado_pin["estado_pin"] != "Activo":
        raise problema(
            409,
            "PIN_BLOQUEADO",
            "El PIN no está habilitado.",
        )

    return estado_pin
