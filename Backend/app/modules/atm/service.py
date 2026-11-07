from datetime import date, datetime
from typing import Any

from sqlalchemy import Connection

from app.core.api.errors import problema
from app.core.database.db import get_engine
from app.core.security.hsm import (
    LONGITUD_PIN,
    ClaveNoAutorizada,
    ErrorHsm,
    Hsm,
    PinBlockInvalido,
    obtener_hsm,
)
from app.modules.atm import repository
from app.modules.atm.hsm.pan_validation import validar_hash_pan
from app.modules.tarjetas.service import pan_de_prueba


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
            "TARJETA_NO_ACTIVA",
            "La tarjeta no está activa.",
        )

    if tarjeta["estado_tarjeta"] == "Bloqueada":
        raise problema(
            423,
            "TARJETA_BLOQUEADA",
            "La tarjeta está bloqueada.",
        )

    if tarjeta["estado_tarjeta"] != "Activa":
        raise problema(
            409,
            "TARJETA_NO_ACTIVA",
            "La tarjeta no está activa.",
        )

    fecha_expiracion = tarjeta["fecha_expiracion"]

    if isinstance(fecha_expiracion, datetime):
        fecha_expiracion = fecha_expiracion.date()

    if fecha_expiracion is None or fecha_expiracion < date.today():
        raise problema(
            409,
            "TARJETA_NO_ACTIVA",
            "La tarjeta no está activa.",
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

    return _validar_estado_pin(
        repository.obtener_estado_pin(conn_seguridad, id_tarjeta)
    )


def _validar_estado_pin(estado_pin: dict[str, Any] | None) -> dict[str, Any]:
    if estado_pin is None:
        raise problema(
            409,
            "PIN_NO_DISPONIBLE",
            "No se puede utilizar el PIN de esta tarjeta.",
        )

    if estado_pin["estado_pin"] == "Bloqueado" or estado_pin["intentos_fallidos"] >= 3:
        raise problema(
            423,
            "PIN_BLOQUEADO",
            "El PIN está bloqueado.",
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
            "PIN_NO_DISPONIBLE",
            "No se puede utilizar el PIN de esta tarjeta.",
        )

    offset = estado_pin.get("pin_offset")
    if (
        not isinstance(offset, str)
        or len(offset) != LONGITUD_PIN
        or not offset.isascii()
        or not offset.isdigit()
        or not estado_pin.get("referencia_clave_pvk")
    ):
        raise problema(
            409,
            "PIN_NO_DISPONIBLE",
            "No se puede utilizar el PIN de esta tarjeta.",
        )
    return estado_pin


def validar_precondiciones_atm(
    conn: Connection,
    conn_seguridad: Connection,
    codigo_atm: str,
    id_tarjeta: int,
) -> None:
    """Valida las condiciones previas a la autenticación ATM."""

    validar_terminal(conn, codigo_atm)
    validar_tarjeta(conn, id_tarjeta)
    validar_estado_pin(conn_seguridad, id_tarjeta)


def verificar_pin_atm(
    hsm: Hsm,
    encrypted_pin_block: str,
    pan: str,
    key_reference: str,
    pin_offset: str,
    referencia_pvk: str,
) -> bool:
    """Delega ISO-4 e IBM 3624 exclusivamente al HSM compartido de TAR-05."""
    try:
        return hsm.verificar_pin(
            encrypted_pin_block, key_reference, pan, pin_offset, referencia_pvk
        )
    except ClaveNoAutorizada:
        raise problema(
            422, "CLAVE_NO_AUTORIZADA", "La referencia de clave no está autorizada."
        ) from None
    except PinBlockInvalido:
        raise problema(
            422, "PIN_BLOCK_INVALIDO", "El PIN Block no es válido."
        ) from None
    except ErrorHsm:
        raise problema(
            503, "HSM_NO_DISPONIBLE", "No se pudo verificar el PIN."
        ) from None


async def autenticar_pin_ficticio_atm(
    conn: Connection,
    id_tarjeta: int,
    encrypted_pin_block: str,
    key_reference: str,
) -> bool:
    """Verifica con el HSM compartido y confirma intentos antes del error HTTP.

    La conexión de SeguridadDB se abre aquí para que lectura bloqueante,
    recuperación del PAN y actualización usen una única transacción.
    """
    tarjeta = validar_tarjeta(conn, id_tarjeta)
    try:
        hsm = obtener_hsm()
    except ErrorHsm:
        raise problema(
            503, "HSM_NO_DISPONIBLE", "No se pudo verificar el PIN."
        ) from None

    with get_engine("seguridad").begin() as conn_pin:
        estado_pin = _validar_estado_pin(
            repository.obtener_pin_para_verificacion(conn_pin, id_tarjeta)
        )
        pan = pan_de_prueba(conn_pin, id_tarjeta, hsm)
        try:
            if not validar_hash_pan(pan, tarjeta["hash_numero_tarjeta"]):
                raise problema(
                    409, "TARJETA_NO_DISPONIBLE", "No se puede verificar esta tarjeta."
                )
            pin_correcto = verificar_pin_atm(
                hsm,
                encrypted_pin_block,
                pan,
                key_reference,
                estado_pin["pin_offset"],
                estado_pin["referencia_clave_pvk"],
            )
        finally:
            del pan
        resultado = repository.guardar_resultado_pin(
            conn=conn_pin, id_tarjeta=id_tarjeta, pin_correcto=pin_correcto
        )
        if resultado is None:
            raise problema(
                423, "PIN_BLOQUEADO", "El PIN no está disponible para autenticación."
            )

    # El commit sucede antes de lanzar estos errores: no revertir los intentos.
    if not pin_correcto:
        if resultado["estado_pin"] == "Bloqueado":
            raise problema(423, "PIN_BLOQUEADO", "El PIN está bloqueado.")
        raise problema(401, "PIN_INCORRECTO", "El PIN ingresado es incorrecto.")
    return True
