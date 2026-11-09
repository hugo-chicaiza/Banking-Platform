"""Límites temporales para asignación de PIN; nunca cambian el pool global."""

from collections.abc import Iterator
from contextlib import closing, contextmanager

import pyodbc
from sqlalchemy import Connection
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from app.core.api.errors import problema, traducir_error_bd

ERRORES_SQL = (SQLAlchemyError, pyodbc.Error)


def error_asignacion(exc: BaseException | None = None, *, ambiguo: bool = False):
    if not ambiguo and isinstance(exc, DBAPIError):
        negocio = traducir_error_bd(exc)
        if (
            isinstance(negocio.detail, dict)
            and negocio.detail.get("code") != "ERROR_INTERNO"
        ):
            return negocio
    mensaje = (
        "No se pudo determinar el resultado de la asignación del PIN. "
        "Requiere reconciliación."
        if ambiguo
        else "No se pudo confirmar la asignación del PIN."
    )
    return problema(503, "PIN_ASIGNACION_NO_CONFIRMADA", mensaje)


def descartar_conexion(conn: Connection) -> None:
    try:
        conn.invalidate()
    except ERRORES_SQL:
        pass  # No sustituir el error original ni reutilizar deliberadamente la conexión.


def rollback_seguro(conn: Connection) -> None:
    try:
        conn.rollback()
    except ERRORES_SQL:
        descartar_conexion(conn)


@contextmanager
def limitar_sql_pin(conn: Connection) -> Iterator[None]:
    """Query timeout ODBC y LOCK_TIMEOUT acotados a la conexión prestada.

    El timeout ODBC limita sentencias; no promete acotar SQLTransact/commit.
    Un fallo al restaurar obliga a descartar la conexión del pool.
    """
    driver = None
    anterior = None
    bloqueo = None
    try:
        try:
            driver = conn.connection.driver_connection
            if driver is None:
                raise SQLAlchemyError("Conexión de asignación no disponible")
            anterior = driver.timeout
            driver.timeout = min(anterior, 15) if anterior > 0 else 15
            with closing(driver.cursor()) as cursor:
                bloqueo = cursor.execute("SELECT @@LOCK_TIMEOUT").fetchval()
                limite = min(bloqueo, 5000) if bloqueo >= 0 else 5000
                cursor.execute(f"SET LOCK_TIMEOUT {int(limite)}")
        except ERRORES_SQL:
            rollback_seguro(conn)
            descartar_conexion(conn)
            raise error_asignacion() from None
        yield
    finally:
        if driver is not None and anterior is not None and not conn.invalidated:
            try:
                if bloqueo is not None:
                    with closing(driver.cursor()) as cursor:
                        cursor.execute(f"SET LOCK_TIMEOUT {int(bloqueo)}")
                driver.timeout = anterior
            except ERRORES_SQL:
                descartar_conexion(conn)
