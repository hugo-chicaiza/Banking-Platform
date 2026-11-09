from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import Connection
from sqlalchemy.exc import SQLAlchemyError

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
from app.core.security.pin_version import PinVersionNoDisponible, version_desde_fecha
from app.modules.atm import repository
from app.modules.atm.hsm.pan_validation import validar_hash_pan
from app.modules.atm.schemas import ATMAuthRequest, CuentaATM
from app.modules.tarjetas import repository as tarjetas_repository
from app.modules.tarjetas.identificacion import hash_pan
from app.modules.tarjetas.service import credito_cumple_plazo, pan_de_prueba


@dataclass(frozen=True)
class AccesoATMValidado:
    """Contexto interno sin PAN, PIN Block ni token; no es una sesión emitida."""

    id_atm: int
    id_tarjeta: int
    titular: str
    cuentas: list[CuentaATM]
    # PIN temporal: sesión restringida, sin cuentas, solo para ATM-06 y ATM-09
    cambio_pin_requerido: bool = False
    pin_version: str | None = None


@dataclass(frozen=True)
class PinVerificado:
    """Resultado de un PIN correcto. requiere_cambio: el PIN es temporal (A-05)."""

    requiere_cambio: bool
    pin_version: str | None = None


def identificar_tarjeta(conn: Connection, numero_tarjeta: str) -> int:
    """Reutiliza el hash binario de TAR-01 y consulta sin enviar el PAN a SQL."""
    id_tarjeta = tarjetas_repository.obtener_id_tarjeta_por_hash(
        conn, hash_pan(numero_tarjeta)
    )
    if id_tarjeta is None:
        raise problema(409, "TARJETA_NO_ACTIVA", "La tarjeta no está activa.")
    return id_tarjeta


async def validar_acceso_atm(
    conn: Connection,
    entrada: ATMAuthRequest,
    *,
    usuario_bloqueo: int | None = None,
    ip: str | None = None,
) -> AccesoATMValidado:
    """Preparación interna: llamar solo después de autenticar la identidad del terminal.

    Valida terminal, tarjeta, PIN y cuenta. No publica rutas ni emite JWT.
    """
    atm = validar_terminal(conn, entrada.codigo_atm)
    id_tarjeta = identificar_tarjeta(conn, entrada.numero_tarjeta.get_secret_value())
    tarjeta = validar_tarjeta(conn, id_tarjeta)
    try:
        verificado = await autenticar_pin_ficticio_atm(
            conn,
            id_tarjeta,
            entrada.encrypted_pin_block.get_secret_value(),
            entrada.key_reference,
        )
    except HTTPException as exc:
        detalle = exc.detail if isinstance(exc.detail, dict) else {}
        if detalle.get("code") == "PIN_BLOQUEADO" and usuario_bloqueo is not None:
            # El contador en SeguridadDB ya quedó confirmado. La tarjeta y su
            # historial se confirman juntos en CooperativaDB, sin revertir intentos.
            # Si falla, el PIN sigue bloqueado y el siguiente acceso reintenta.
            try:
                with get_engine("cooperativa").begin() as conn_bloqueo:
                    repository.bloquear_tarjeta_por_pin(
                        conn_bloqueo, id_tarjeta, atm["id_canal"], usuario_bloqueo, ip
                    )
            except SQLAlchemyError:
                raise problema(
                    503,
                    "BLOQUEO_NO_CONFIRMADO",
                    "No se pudo completar el bloqueo de la tarjeta.",
                ) from None
        raise
    titular = " ".join(
        parte
        for parte in (tarjeta["nombres_titular"], tarjeta["apellidos_titular"])
        if parte
    )
    if verificado.requiere_cambio:
        # A-05: con PIN temporal solo se permite cambiarlo (ATM-06); sin cuentas
        return AccesoATMValidado(
            atm["id_atm"],
            id_tarjeta,
            titular,
            [],
            cambio_pin_requerido=True,
            pin_version=verificado.pin_version,
        )
    if tarjeta["estado_tarjeta"] == "Generada":
        # Crédito que ya cumplió el plazo (validar_tarjeta lo comprobó)
        _activar_credito(id_tarjeta, atm["id_canal"], usuario_bloqueo, ip)
    cuentas = [
        CuentaATM(
            id_cuenta=fila["id_cuenta"],
            numero_cuenta_enmascarado="*" * max(len(fila["numero_cuenta"]) - 4, 4)
            + fila["numero_cuenta"][-4:],
            tipo_cuenta=fila["tipo_cuenta"],
        )
        for fila in repository.obtener_cuentas_autorizadas(conn, id_tarjeta)
    ]
    if not cuentas:
        raise problema(
            409, "CUENTA_NO_ACTIVA", "No hay cuentas habilitadas para operar."
        )
    return AccesoATMValidado(
        atm["id_atm"], id_tarjeta, titular, cuentas, pin_version=verificado.pin_version
    )


def _activar_credito(
    id_tarjeta: int, id_canal: int, usuario: int | None, ip: str | None
) -> None:
    """A-05: activa la tarjeta de crédito Generada que cumplió los 3 días laborables."""
    if usuario is None:
        raise problema(409, "TARJETA_NO_ACTIVA", "La tarjeta no está activa.")
    try:
        with get_engine("cooperativa").begin() as conn_activacion:
            repository.activar_tarjeta_credito(
                conn_activacion, id_tarjeta, id_canal, usuario, ip
            )
    except SQLAlchemyError:
        raise problema(
            503,
            "ACTIVACION_NO_CONFIRMADA",
            "No se pudo completar la activación de la tarjeta.",
        ) from None


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

    if tarjeta["estado_tarjeta"] == "Generada":
        # A-05: la de débito se acepta para el primer cambio de PIN (se confirma con
        # TarjetaPIN.RequiereCambio); la de crédito, solo si ya cumplió el plazo
        if tarjeta.get("tipo_tarjeta") == "Credito":
            fecha_emision = tarjeta.get("fecha_emision")
            if isinstance(fecha_emision, datetime):
                fecha_emision = fecha_emision.date()
            if fecha_emision is None or not credito_cumple_plazo(conn, fecha_emision):
                raise problema(
                    409,
                    "TARJETA_NO_ACTIVA",
                    "La tarjeta no está activa.",
                )
        elif tarjeta.get("tipo_tarjeta") != "Debito":
            raise problema(
                409,
                "TARJETA_NO_ACTIVA",
                "La tarjeta no está activa.",
            )
    elif tarjeta["estado_tarjeta"] != "Activa":
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
) -> PinVerificado:
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
        try:
            pin_version = version_desde_fecha(estado_pin.get("fecha_asignacion"))
        except PinVersionNoDisponible:
            raise problema(
                503,
                "PIN_NO_DISPONIBLE",
                "No se puede verificar esta asignación de PIN.",
            ) from None
        requiere_cambio = bool(estado_pin.get("requiere_cambio"))
        if (
            tarjeta["estado_tarjeta"] == "Generada"
            and tarjeta.get("tipo_tarjeta") == "Debito"
            and not requiere_cambio
        ):
            # Débito Generada sin PIN temporal: no hay primer cambio que hacer
            raise problema(409, "TARJETA_NO_ACTIVA", "La tarjeta no está activa.")
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
    return PinVerificado(requiere_cambio=requiere_cambio, pin_version=pin_version)
