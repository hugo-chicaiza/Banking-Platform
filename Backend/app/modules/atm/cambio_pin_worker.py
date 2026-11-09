"""Una ejecucion acotada del WebJob. Sin scheduler, hilos ni HSM propios.

El limite de intentos se reinicia en cada ejecucion. Auditoria es observabilidad,
no almacenamiento de presupuesto ni sustituto del diario de coordinacion.
"""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from time import monotonic, sleep

import pyodbc
from fastapi import HTTPException
from sqlalchemy import Connection, text
from sqlalchemy.exc import SQLAlchemyError

from app.core.config.settings import Settings, get_settings
from app.core.database.db import get_engine
from app.core.database.procedimientos import ejecutar_con_salidas
from app.core.database.session_scope import ERRORES_SQL, sesion_sql_acotada
from app.core.security import audit
from app.modules.atm.cambio_pin_service import (
    RecuperacionFueraVentana,
    RecuperacionNoConfirmada,
    recuperar_cambio_pin,
)

logger = logging.getLogger(__name__)
RECURSO = "ATM06:RecuperacionPeriodica:v1"
TABLA = "Tarjetas.CambioPINATMOperacion"


@dataclass(frozen=True)
class Politica:
    min_edad: int = 30
    max_edad: int = 1800
    lote: int = 20
    presupuesto: float = 45
    intentos: int = 3
    espera: float = 1

    def __post_init__(self):
        if not (
            0 <= self.min_edad < self.max_edad <= 604800
            and 1 <= self.lote <= 200
            and 1 <= self.presupuesto <= 300
            and 1 <= self.intentos <= 10
            and 0 <= self.espera <= 30
        ):
            raise ValueError("Politica de recuperacion invalida")

    @classmethod
    def desde_settings(cls, settings: Settings) -> "Politica":
        return cls(
            settings.atm_pin_recovery_min_age_seconds,
            settings.atm_pin_recovery_max_age_seconds,
            settings.atm_pin_recovery_batch_size,
            settings.atm_pin_recovery_budget_seconds,
            settings.atm_pin_recovery_max_attempts_per_run,
            settings.atm_pin_recovery_retry_delay_seconds,
        )


class LeasePerdida(Exception):
    pass


@contextmanager
def lease() -> Iterator[Connection | None]:
    """Bloqueo de sesion dedicado; no retener una transaccion entre bases."""
    if pyodbc.pooling:
        # Invocar desde el CLI independiente, que prepara ODBC antes de conectar.
        logger.error("ATM06_RECOVERY_ALERT reason=ODBC_POOLING_ENABLED")
        raise LeasePerdida()
    with get_engine("seguridad").connect() as conn, sesion_sql_acotada(conn):
        try:
            with conn.begin():
                resultado = ejecutar_con_salidas(
                    conn,
                    """
                DECLARE @r int;
                EXEC @r=sys.sp_getapplock @Resource=?, @LockMode='Exclusive',
                    @LockOwner='Session', @LockTimeout=0, @DbPrincipal='public';
                SELECT @r AS Resultado;
            """,
                    (RECURSO,),
                )["Resultado"]
        except (*ERRORES_SQL, RuntimeError):
            # El servidor puede haber concedido el lock antes de perderse la respuesta.
            conn.invalidate()
            raise LeasePerdida() from None
        if resultado == -1:
            yield None
            return
        if resultado not in (0, 1):
            conn.invalidate()
            raise LeasePerdida()
        try:
            yield conn
        finally:
            # No permitir reconectar y creer que se conserva la titularidad.
            if conn.invalidated:
                logger.error("ATM06_RECOVERY_ALERT reason=LEASE_LOST")
                raise LeasePerdida()
            else:
                try:
                    conn.rollback()
                    with conn.begin():
                        liberado = ejecutar_con_salidas(
                            conn,
                            """
                            DECLARE @r int;
                            EXEC @r=sys.sp_releaseapplock @Resource=?,
                                @LockOwner='Session', @DbPrincipal='public';
                            SELECT @r AS Resultado;
                        """,
                            (RECURSO,),
                        )["Resultado"]
                    if liberado < 0:
                        conn.invalidate()
                        raise LeasePerdida()
                except (*ERRORES_SQL, RuntimeError):
                    conn.invalidate()
                    raise LeasePerdida() from None


def comprobar_lease(conn: Connection) -> None:
    if conn.invalidated:
        raise LeasePerdida()
    try:
        modo = conn.scalar(
            text("SELECT APPLOCK_MODE('public', :recurso, 'Session')"),
            {"recurso": RECURSO},
        )
    finally:
        conn.rollback()
    if modo != "Exclusive":
        raise LeasePerdida()


def pendientes(conn: Connection, politica: Politica) -> tuple[list[str], int]:
    params = {
        "min": politica.min_edad,
        "max": politica.max_edad,
        "limite": politica.lote,
    }
    try:
        vencidas = conn.scalar(
            text("""
            SELECT COUNT_BIG(*) FROM Tarjetas.CambioPINATMOperacion
            WHERE FechaFinalizacionUTC IS NULL
              AND FechaInicioUTC < DATEADD(second, -:max, SYSUTCDATETIME());
        """),
            params,
        )
        filas = (
            conn.execute(
                text("""
            SELECT TOP (:limite) IdOperacion FROM Tarjetas.CambioPINATMOperacion
            WHERE FechaFinalizacionUTC IS NULL
              AND Estado IN ('PIN_CONFIRMADO','COOP_CONFIRMADA')
              AND FechaInicioUTC <= DATEADD(second, -:min, SYSUTCDATETIME())
              AND FechaInicioUTC >= DATEADD(second, -:max, SYSUTCDATETIME())
            ORDER BY FechaInicioUTC, IdOperacion;
        """),
                params,
            )
            .scalars()
            .all()
        )
        return [str(f) for f in filas], int(vencidas or 0)
    finally:
        conn.rollback()


def elegible(conn: Connection, operacion: str, politica: Politica) -> bool:
    try:
        return (
            conn.scalar(
                text("""
            SELECT 1 FROM Tarjetas.CambioPINATMOperacion
            WHERE IdOperacion=:id AND FechaFinalizacionUTC IS NULL
              AND Estado IN ('PIN_CONFIRMADO','COOP_CONFIRMADA')
              AND FechaInicioUTC <= DATEADD(second, -:min, SYSUTCDATETIME())
              AND FechaInicioUTC >= DATEADD(second, -:max, SYSUTCDATETIME());
        """),
                {"id": operacion, "min": politica.min_edad, "max": politica.max_edad},
            )
            is not None
        )
    finally:
        conn.rollback()


def observar(
    operacion: str, accion: str, resultado: str, *, ejecutor: str = "WEBJOB"
) -> bool:
    """UsuarioID NULL: ejecutor tecnico, no suplanta al actor ni a WorkOS."""
    evento = audit.EventoAuditoria(
        accion=accion,
        tabla=TABLA,
        id_registro=operacion,
        resultado="Exitoso" if resultado in {"OK", "INICIO"} else "Fallido",
        usuario=None,
        ip=None,
        roles="",
        descripcion=f"ejecutor=ATM06_{ejecutor}; resultado={resultado}",
    )
    try:
        audit._persistir(evento)
        return True
    except ERRORES_SQL:
        logger.error(
            "ATM06_RECOVERY_ALERT reason=AUDIT_UNAVAILABLE operation=%s", operacion
        )
        return False


def ejecutar_lote(politica: Politica) -> int:
    inicio = monotonic()
    errores = False
    intentos = completadas = 0
    try:
        with lease() as conn:
            if conn is None:
                logger.info("ATM06_RECOVERY status=LOCK_BUSY")
                return 0
            comprobar_lease(conn)
            operaciones, vencidas = pendientes(conn, politica)
            logger.info(
                "ATM06_RECOVERY status=STARTED selected=%s expired=%s max_attempts_per_operation_this_run=%s",
                len(operaciones),
                vencidas,
                politica.intentos,
            )
            if vencidas:
                logger.error(
                    "ATM06_RECOVERY_ALERT reason=EXPIRED_PENDING count=%s", vencidas
                )
                errores = True
            for operacion in operaciones:
                for intento in range(1, politica.intentos + 1):
                    if monotonic() - inicio >= politica.presupuesto:
                        logger.warning("ATM06_RECOVERY reason=BUDGET_EXHAUSTED")
                        break
                    comprobar_lease(conn)
                    if not elegible(conn, operacion, politica):
                        break
                    intentos += 1
                    errores |= not observar(operacion, "ATM06_REC_INICIO", "INICIO")
                    # Fallo no significa PIN incorrecto: nunca tocar sus contadores.
                    try:
                        recuperar_cambio_pin(
                            operacion, max_edad_segundos=politica.max_edad
                        )
                    except HTTPException as exc:
                        transitorio = (
                            isinstance(exc, RecuperacionNoConfirmada)
                            and exc.reintentable
                        )
                        categoria = (
                            "VENTANA_AGOTADA"
                            if isinstance(exc, RecuperacionFueraVentana)
                            else "TRANSITORIO"
                            if transitorio
                            else "INCONSISTENTE"
                        )
                        errores |= not observar(operacion, "ATM06_REC_FALLO", categoria)
                        if not transitorio or intento == politica.intentos:
                            logger.error(
                                "ATM06_RECOVERY_ALERT reason=%s operation=%s attempts_this_run=%s",
                                categoria,
                                operacion,
                                intento,
                            )
                            errores = True
                            break
                        if (
                            monotonic() - inicio + politica.espera
                            >= politica.presupuesto
                        ):
                            logger.error(
                                "ATM06_RECOVERY_ALERT reason=RETRY_BUDGET_EXHAUSTED operation=%s",
                                operacion,
                            )
                            errores = True
                            break
                        sleep(politica.espera)
                    else:
                        completadas += 1
                        errores |= not observar(operacion, "ATM06_REC_OK", "OK")
                        logger.info(
                            "ATM06_RECOVERY status=COMPLETED operation=%s", operacion
                        )
                        break
                if monotonic() - inicio >= politica.presupuesto:
                    break
            comprobar_lease(conn)
    except (LeasePerdida, SQLAlchemyError):
        logger.error("ATM06_RECOVERY_ALERT reason=WORKER_UNAVAILABLE")
        return 1
    except Exception:  # noqa: BLE001 -- frontera CLI: salida no cero sin filtrar secretos.
        # No serializar errores inesperados que puedan incluir valores internos.
        logger.error("ATM06_RECOVERY_ALERT reason=UNEXPECTED_FAILURE")
        return 1
    logger.info(
        "ATM06_RECOVERY status=FINISHED attempts_this_run=%s completed=%s",
        intentos,
        completadas,
    )
    return int(errores)


def ejecutar_configurado() -> int:
    settings = get_settings()
    if not settings.atm_pin_recovery_enabled:
        logger.info("ATM06_RECOVERY status=DISABLED")
        return 0
    return ejecutar_lote(Politica.desde_settings(settings))
