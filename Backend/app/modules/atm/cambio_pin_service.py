"""Coordinacion durable ATM-06; la recuperacion nunca recibe bloques PIN."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import Connection
from sqlalchemy.exc import DBAPIError

from app.core.api.errors import problema
from app.core.database.db import get_engine
from app.core.database.session_scope import ERRORES_SQL, sesion_sql_acotada
from app.core.security.hsm import ErrorHsm, PinDebil, obtener_hsm
from app.core.security.pin_version import PinVersionNoDisponible, version_desde_fecha
from app.modules.atm import cambio_pin_repository as repo
from app.modules.atm import repository, service
from app.modules.atm.schemas import AtmCambioPinRequest
from app.modules.atm.session import SesionATM, _sesion_invalida
from app.modules.atm.terminal_auth import TerminalAutenticado, revalidar_terminal
from app.modules.tarjetas.repository import guardar_pin_generado
from app.modules.tarjetas.service import _error_hsm

ERRORES_COORDINACION = (*ERRORES_SQL, PinVersionNoDisponible)


class RecuperacionNoConfirmada(HTTPException):
    """Clasificacion interna, sin cambiar el contrato publico de ProblemDetails."""

    def __init__(self, *, reintentable: bool = False):
        error = problema(
            503,
            "CAMBIO_PIN_NO_CONFIRMADO",
            "No se pudo confirmar el cambio de PIN. Requiere reconciliación antes de repetirlo.",
        )
        super().__init__(status_code=error.status_code, detail=error.detail)
        self.reintentable = reintentable


class RecuperacionFueraVentana(RecuperacionNoConfirmada):
    """El ejecutor automatico no puede avanzar; requiere intervencion manual."""


def no_confirmado(*, reintentable: bool = False) -> RecuperacionNoConfirmada:
    return RecuperacionNoConfirmada(reintentable=reintentable)


def error_transitorio(exc: BaseException) -> bool:
    """Solo clasificar errores conocidos; nunca registrar el texto SQL/parametros."""
    import re

    original = exc.orig if isinstance(exc, DBAPIError) else exc
    args = getattr(original, "args", ())
    estado = str(args[0]) if args else ""
    codigos = set(re.findall(r"\((\d+)\)", " ".join(str(v) for v in args)))
    return (
        estado.startswith("08")
        or estado in {"HYT00", "HYT01", "40001"}
        or bool(codigos & {"1205", "1222", "40197", "40501", "40613"})
    )


@contextmanager
def _conexiones() -> Iterator[tuple[Connection, Connection]]:
    with (
        get_engine("cooperativa").connect() as coop,
        get_engine("seguridad").connect() as seg,
        sesion_sql_acotada(coop),
        sesion_sql_acotada(seg),
    ):
        yield coop, seg


def _version(pin: dict[str, Any]) -> str:
    return version_desde_fecha(pin.get("fecha_asignacion"))


def _validar_evidencia(op: dict[str, Any], marca: dict[str, Any] | None) -> None:
    if (
        marca is None
        or any(
            marca[m] != op[o]
            for m, o in (
                ("IdTarjeta", "ID_Tarjeta"),
                ("VersionPIN", "VersionNueva"),
                ("IdATM", "IdATM"),
                ("IdCanal", "IdCanal"),
                ("ActorAuditoria", "ActorAuditoria"),
                ("RequiereActivacion", "RequiereActivacion"),
            )
        )
        or str(marca["IdOperacion"]).lower() != str(op["IdOperacion"]).lower()
    ):
        raise no_confirmado()


def _leer_bloqueado(coop: Connection, seg: Connection, tarjeta: int, operacion: str):
    repo.bloquear_tarjeta(coop, tarjeta)
    pin = repository.obtener_pin_para_verificacion(seg, tarjeta)
    op = repo.leer_operacion(seg, operacion)
    if (
        op is None
        or pin is None
        or op["ID_Tarjeta"] != tarjeta
        or _version(pin) != version_desde_fecha(op["VersionNueva"])
    ):
        raise no_confirmado()
    service._validar_estado_pin(pin)
    if not repository.sesion_atm_revocada(seg, str(op["JtiOrigen"])):
        # Una limpieza legitima de revocaciones vencidas no debe impedir
        # reconciliar. Antes de expirar, la revocacion sigue siendo obligatoria.
        expiracion = op.get("ExpiracionSesionUTC")
        if not isinstance(expiracion, datetime) or expiracion.replace(
            tzinfo=UTC
        ) > datetime.now(UTC):
            raise no_confirmado()
    return op, pin


def recuperar_cambio_pin(
    operacion: str, *, max_edad_segundos: int | None = None
) -> None:
    """Entrada interna de reconciliacion; no expuesta como bypass de sesiones.

    Puede ejecutarse desde otro proceso. Un error exige una nueva invocacion
    supervisada; no hay reintentos ciegos ni operaciones criptograficas aqui.
    """
    try:
        with get_engine("seguridad").connect() as lectura, sesion_sql_acotada(lectura):
            tarjeta = repo.identificar_operacion(lectura, operacion)
        if tarjeta is None:
            raise no_confirmado()
        with _conexiones() as (coop, seg), coop.begin(), seg.begin():
            op, pin = _leer_bloqueado(coop, seg, tarjeta, operacion)
            marca = repo.leer_marcador(coop, operacion)
            if op["Estado"] == "COMPLETADA":
                _validar_evidencia(op, marca)
                if pin["requiere_cambio"]:
                    raise no_confirmado()
                return
            if max_edad_segundos is not None and not repo.dentro_ventana(
                seg, operacion, max_edad_segundos
            ):
                raise RecuperacionFueraVentana()
            if not pin["requiere_cambio"]:
                raise no_confirmado()
            actual = service.validar_tarjeta(coop, tarjeta)
            if marca is None:
                if (
                    op["Estado"] != "PIN_CONFIRMADO"
                    or (
                        op["RequiereActivacion"]
                        and (
                            actual["estado_tarjeta"] != "Generada"
                            or actual["tipo_tarjeta"] != "Debito"
                        )
                    )
                    or (
                        not op["RequiereActivacion"]
                        and actual["estado_tarjeta"] != "Activa"
                    )
                ):
                    raise no_confirmado()
                repo.aplicar_cooperativa(coop, op)
                marca = repo.leer_marcador(coop, operacion)
            _validar_evidencia(op, marca)
            # Mantener el bloqueo del PIN hasta confirmar CooperativaDB.
            coop.commit()
            if op["Estado"] == "PIN_CONFIRMADO":
                repo.avanzar(seg, operacion)

        # Releer ambas bases; no habilitar a partir de evidencia solo en memoria.
        with _conexiones() as (coop, seg), coop.begin(), seg.begin():
            op, pin = _leer_bloqueado(coop, seg, tarjeta, operacion)
            _validar_evidencia(op, repo.leer_marcador(coop, operacion))
            actual = service.validar_tarjeta(coop, tarjeta)
            if actual["estado_tarjeta"] != "Activa":
                raise no_confirmado()
            if op["Estado"] == "COMPLETADA" and not pin["requiere_cambio"]:
                return
            if max_edad_segundos is not None and not repo.dentro_ventana(
                seg, operacion, max_edad_segundos
            ):
                raise RecuperacionFueraVentana()
            if op["Estado"] != "COOP_CONFIRMADA" or not pin["requiere_cambio"]:
                raise no_confirmado()
            repo.finalizar(seg, op)
    except ERRORES_SQL as exc:
        raise no_confirmado(reintentable=error_transitorio(exc)) from None
    except PinVersionNoDisponible:
        raise no_confirmado() from None


def cambiar_pin(
    sesion: SesionATM,
    terminal: TerminalAutenticado,
    entrada: AtmCambioPinRequest,
    ip: str | None,
) -> None:
    revalidar_terminal(terminal)
    operacion = str(uuid4())
    fallo: HTTPException | None = None
    try:
        with _conexiones() as (coop, seg), coop.begin():
            repo.bloquear_tarjeta(coop, sesion.id_tarjeta)
            atm = service.validar_terminal(coop, terminal.codigo_atm)
            if atm["id_atm"] != sesion.id_atm:
                raise problema(
                    403, "TERMINAL_NO_AUTORIZADO", "El terminal no permite operar."
                )
            tarjeta = service.validar_tarjeta(coop, sesion.id_tarjeta)
            with seg.begin():
                pin = service._validar_estado_pin(
                    repository.obtener_pin_para_verificacion(seg, sesion.id_tarjeta)
                )
                if (
                    sesion.pin_version is None
                    or _version(pin) != sesion.pin_version
                    or datetime.now(UTC) >= sesion.fecha_expiracion
                    or repository.sesion_atm_revocada(seg, sesion.jti)
                ):
                    raise _sesion_invalida()
                if repo.hay_pendiente(seg, sesion.id_tarjeta):
                    raise no_confirmado()
                activar = tarjeta["estado_tarjeta"] == "Generada"
                if activar and (
                    tarjeta["tipo_tarjeta"] != "Debito"
                    or not pin["requiere_cambio"]
                    or not sesion.cambio_pin_requerido
                ):
                    raise problema(
                        409, "TARJETA_NO_ACTIVA", "La tarjeta no permite el cambio."
                    )
                hsm = obtener_hsm()
                nuevo: tuple[str, str] | None = None
                pan = service.pan_de_prueba(seg, sesion.id_tarjeta, hsm)
                try:
                    if not service.validar_hash_pan(
                        pan, tarjeta["hash_numero_tarjeta"]
                    ):
                        raise no_confirmado()
                    correcto = service.verificar_pin_atm(
                        hsm,
                        entrada.encrypted_pin_block_actual.get_secret_value(),
                        pan,
                        entrada.key_reference,
                        pin["pin_offset"],
                        pin["referencia_clave_pvk"],
                    )
                    if correcto:
                        nuevo = hsm.generar_offset(
                            entrada.encrypted_pin_block_nuevo.get_secret_value(),
                            entrada.key_reference,
                            pan,
                        )
                        if service.verificar_pin_atm(
                            hsm,
                            entrada.encrypted_pin_block_nuevo.get_secret_value(),
                            pan,
                            entrada.key_reference,
                            pin["pin_offset"],
                            pin["referencia_clave_pvk"],
                        ):
                            raise PinDebil()
                finally:
                    del pan
                if not correcto:
                    resultado = repository.guardar_resultado_pin(
                        seg, sesion.id_tarjeta, False
                    )
                    bloqueado = (
                        resultado is None or resultado["estado_pin"] == "Bloqueado"
                    )
                    fallo = problema(
                        423 if bloqueado else 401,
                        "PIN_BLOQUEADO" if bloqueado else "PIN_INCORRECTO",
                        "El PIN está bloqueado."
                        if bloqueado
                        else "El PIN ingresado es incorrecto.",
                    )
                else:
                    if nuevo is None:
                        raise no_confirmado()
                    offset, pvk = nuevo
                    guardar_pin_generado(seg, sesion.id_tarjeta, offset, pvk, True)
                    repo.registrar_fecha_cambio(seg, sesion.id_tarjeta)
                    repo.insertar_operacion(
                        seg,
                        {
                            "operacion": operacion,
                            "tarjeta": sesion.id_tarjeta,
                            "atm": sesion.id_atm,
                            "canal": atm["id_canal"],
                            "actor": terminal.audit_user_id,
                            "ip": ip,
                            "jti": sesion.jti,
                            "expiracion": sesion.fecha_expiracion.astimezone(
                                UTC
                            ).replace(tzinfo=None),
                            "anterior": pin["fecha_asignacion"],
                            "activar": activar,
                        },
                    )
                    repository.revocar_sesion_atm(
                        seg, sesion.jti, sesion.fecha_expiracion
                    )
            if fallo is not None and fallo.status_code == 423:
                repository.bloquear_tarjeta_por_pin(
                    coop, sesion.id_tarjeta, atm["id_canal"], terminal.audit_user_id, ip
                )
        if fallo is not None:
            raise fallo
        recuperar_cambio_pin(operacion)
    except PinDebil:
        raise problema(422, "PIN_DEBIL", "El nuevo PIN no está permitido.") from None
    except ErrorHsm as exc:
        raise _error_hsm(exc, "HSM_NO_DISPONIBLE") from None
    except ERRORES_COORDINACION:
        raise no_confirmado() from None
