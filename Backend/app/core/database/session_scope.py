"""Estado SQL temporal de una conexión prestada, sin configurar el pool global."""

from collections.abc import Iterator
from contextlib import closing, contextmanager

import pyodbc
from sqlalchemy import Connection
from sqlalchemy.exc import SQLAlchemyError

ERRORES_SQL = (SQLAlchemyError, pyodbc.Error)


def _descartar(conn: Connection) -> None:
    try:
        conn.invalidate()
    except ERRORES_SQL:
        pass  # Una conexión ya invalidada/cerrada tampoco debe ocultar el error original.


@contextmanager
def sesion_sql_acotada(conn: Connection) -> Iterator[None]:
    """Captura NOCOUNT/LOCK_TIMEOUT y limita las sentencias ODBC a 15 segundos.

    Mantiene límites previos más estrictos. El llamador conserva la gestión de su
    transacción. SQLTransact/commit no tiene garantizado ese timeout de sentencias.
    Los cursores se cierran sin usar su context manager, que puede hacer commit.
    """
    driver = None
    timeout_previo = None
    estado = None
    try:
        try:
            driver = conn.connection.driver_connection
            if driver is None:
                raise SQLAlchemyError("Conexión no disponible")
            timeout_previo = driver.timeout
            driver.timeout = min(timeout_previo, 15) if timeout_previo > 0 else 15
            with closing(driver.cursor()) as cursor:
                estado = cursor.execute(
                    "SELECT @@LOCK_TIMEOUT, @@OPTIONS & 512"
                ).fetchone()
                if (
                    estado is None
                    or len(estado) != 2
                    or type(estado[0]) is not int
                    or estado[0] < -1
                    or estado[1] not in (0, 512)
                ):
                    raise SQLAlchemyError("Estado de sesión no disponible")
                bloqueo = min(estado[0], 5000) if estado[0] >= 0 else 5000
                cursor.execute(f"SET LOCK_TIMEOUT {bloqueo}")
        except ERRORES_SQL:
            _descartar(conn)
            raise SQLAlchemyError("No se pudo preparar la conexión") from None
        yield
    except ERRORES_SQL:
        # El begin() del llamador ya intenta rollback, incluso si falló el commit.
        # Si ese rollback no pudo completarse, no devolver la conexión al pool.
        try:
            conn.rollback()
        except ERRORES_SQL:
            _descartar(conn)
        raise
    finally:
        if driver is not None and timeout_previo is not None and not conn.invalidated:
            try:
                if estado is not None:
                    with closing(driver.cursor()) as cursor:
                        cursor.execute(
                            "SET NOCOUNT ON" if estado[1] else "SET NOCOUNT OFF"
                        )
                        cursor.execute(f"SET LOCK_TIMEOUT {estado[0]}")
                driver.timeout = timeout_previo
            except ERRORES_SQL:
                _descartar(conn)
