from datetime import date, datetime
from typing import Any

from sqlalchemy import Connection

from app.core.api.errors import problema
from app.core.database.db import get_engine
from app.modules.atm import repository
from app.modules.atm.hsm.interface import (
    HsmInterface,
    PinVerificationRequest,
)
from app.modules.atm.hsm.pan_validation import validar_hash_pan
from app.modules.atm.hsm.test_pan_repository import PanFicticioRepository
from app.modules.atm.hsm.validation import derivar_validation_data


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

    if estado_pin["estado_pin"] == "Bloqueado":
        raise problema(
            423,
            "PIN_BLOQUEADO",
            "El PIN está bloqueado.",
        )

    if estado_pin["estado_pin"] != "Activo":
        raise problema(
            409,
            "PIN_NO_DISPONIBLE",
            "No se puede utilizar el PIN de esta tarjeta.",
        )

    if not estado_pin.get("pin_offset"):
        raise problema(
            409,
            "PIN_NO_DISPONIBLE",
            "La tarjeta no tiene un PIN Offset registrado.",
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


async def verificar_pin_atm(
    hsm: HsmInterface,
    encrypted_pin_block: bytes,
    pan: str,
    key_reference: str,
    validation_data: str,
    pin_offset: str,
) -> bool:
    """Verifica el PIN mediante el HSM simulado."""

    solicitud = PinVerificationRequest(
        encrypted_pin_block=encrypted_pin_block,
        pan=pan,
        key_reference=key_reference,
        validation_data=validation_data,
        pin_offset=pin_offset,
    )

    return await hsm.verify_pin(solicitud)


async def autenticar_pin_atm(
    conn_seguridad: Connection,
    hsm: HsmInterface,
    id_tarjeta: int,
    encrypted_pin_block: bytes,
    pan: str,
    key_reference: str,
    validation_data: str,
) -> bool:
    """Verifica el PIN de una tarjeta ficticia mediante el HSM simulado."""

    # 1. Consultar el estado y Offset en SeguridadDB.
    estado_pin = validar_estado_pin(
        conn_seguridad,
        id_tarjeta,
    )

    # 2. Recuperar el Offset almacenado.
    pin_offset = estado_pin["pin_offset"]

    # 3. Solicitar la verificación al HSM.
    return await verificar_pin_atm(
        hsm=hsm,
        encrypted_pin_block=encrypted_pin_block,
        pan=pan,
        key_reference=key_reference,
        validation_data=validation_data,
        pin_offset=pin_offset,
    )


async def autenticar_pin_ficticio_atm(
    conn: Connection,
    conn_seguridad: Connection,
    hsm: HsmInterface,
    repositorio_pan: PanFicticioRepository,
    id_tarjeta: int,
    encrypted_pin_block: bytes,
    key_reference: str,
) -> bool:
    """Verifica el PIN ficticio y actualiza los intentos de forma transaccional."""

    pan = repositorio_pan.obtener(id_tarjeta)

    if pan is None:
        raise problema(
            409,
            "TARJETA_NO_DISPONIBLE",
            "No se puede verificar esta tarjeta.",
        )

    tarjeta = validar_tarjeta(conn, id_tarjeta)

    if not validar_hash_pan(
        pan,
        tarjeta["hash_numero_tarjeta"],
    ):
        raise problema(
            409,
            "TARJETA_NO_DISPONIBLE",
            "No se puede verificar esta tarjeta.",
        )

    validation_data = derivar_validation_data(pan)

    # La conexión de SeguridadDB debe permanecer dentro
    # de esta transacción durante toda la verificación.
    with get_engine("seguridad").begin() as conn_pin:
        estado_pin = repository.obtener_pin_para_verificacion(
            conn_pin,
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

        if estado_pin["estado_pin"] == "Bloqueado":
            raise problema(
                423,
                "PIN_BLOQUEADO",
                "El PIN está bloqueado.",
            )

        if estado_pin["estado_pin"] != "Activo":
            raise problema(
                409,
                "PIN_NO_DISPONIBLE",
                "No se puede utilizar el PIN de esta tarjeta.",
            )

        if not estado_pin["pin_offset"]:
            raise problema(
                409,
                "PIN_NO_DISPONIBLE",
                "La tarjeta no tiene un PIN Offset registrado.",
            )

        pin_correcto = await verificar_pin_atm(
            hsm=hsm,
            encrypted_pin_block=encrypted_pin_block,
            pan=pan,
            key_reference=key_reference,
            validation_data=validation_data,
            pin_offset=estado_pin["pin_offset"],
        )

        resultado = repository.guardar_resultado_pin(
            conn=conn_pin,
            id_tarjeta=id_tarjeta,
            pin_correcto=pin_correcto,
        )

        if resultado is None:
            raise problema(
                423,
                "PIN_BLOQUEADO",
                "El PIN no está disponible para autenticación.",
            )

    # Al salir del bloque sin excepción, SQLAlchemy confirma el COMMIT.
    # Los errores HTTP se generan después para no revertir los intentos.

    if not pin_correcto:
        if resultado["estado_pin"] == "Bloqueado":
            raise problema(
                423,
                "PIN_BLOQUEADO",
                "El PIN está bloqueado.",
            )

        raise problema(
            401,
            "PIN_INCORRECTO",
            "El PIN ingresado es incorrecto.",
        )

    return True
