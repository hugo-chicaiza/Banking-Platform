"""Estado de sesión y errores SQL con dobles ODBC, sin conexiones externas."""

from typing import cast
from unittest.mock import MagicMock

import pyodbc
import pytest
from sqlalchemy import Connection
from sqlalchemy.exc import SQLAlchemyError

from app.core.database.session_scope import sesion_sql_acotada
from tests.pin_version import DriverLimitesSQL


@pytest.fixture
def conexion():
    conn = MagicMock()
    conn.invalidated = False
    driver = DriverLimitesSQL()
    conn.connection.driver_connection = driver
    conn.invalidate.side_effect = lambda: setattr(conn, "invalidated", True)
    return conn, driver


@pytest.mark.parametrize("nocount", [False, True])
@pytest.mark.parametrize("query,lock", [(0, -1), (2, 100), (30, 20000), (0, 0)])
@pytest.mark.parametrize("fallo", [False, True])
def test_restaura_estado_exacto_y_respeta_limites(
    conexion, nocount, query, lock, fallo
):
    conn, driver = conexion
    driver.nocount, driver.timeout, driver.lock_timeout = nocount, query, lock

    def ejecutar():
        with sesion_sql_acotada(cast(Connection, conn)):
            assert driver.timeout == (min(query, 15) if query > 0 else 15)
            assert driver.lock_timeout == (min(lock, 5000) if lock >= 0 else 5000)
            driver.cursor().execute("SET NOCOUNT OFF" if nocount else "SET NOCOUNT ON")
            if fallo:
                raise ValueError("error de negocio local")

    if fallo:
        with pytest.raises(ValueError):
            ejecutar()
    else:
        ejecutar()
    assert (driver.nocount, driver.timeout, driver.lock_timeout) == (
        nocount,
        query,
        lock,
    )
    conn.commit.assert_not_called()
    conn.invalidate.assert_not_called()


@pytest.mark.parametrize("state", ["HYT00", "40001", "08S01"])
def test_error_sql_restaura_y_no_reintenta(conexion, state):
    conn, driver = conexion
    operacion = MagicMock(side_effect=pyodbc.Error(state, "dato privado"))
    with pytest.raises(pyodbc.Error), sesion_sql_acotada(conn):
        driver.cursor().execute("SET NOCOUNT ON")
        operacion()
    assert (driver.nocount, driver.timeout, driver.lock_timeout) == (False, 0, -1)
    operacion.assert_called_once()
    conn.rollback.assert_called_once()
    conn.commit.assert_not_called()


@pytest.mark.parametrize("sentencia", ["SET NOCOUNT OFF", "SET LOCK_TIMEOUT -1"])
def test_restauracion_fallida_descarta_conexion(conexion, monkeypatch, sentencia):
    conn, driver = conexion
    cursor = driver.cursor()
    original = cursor.execute

    def ejecutar(sql):
        if sql == sentencia:
            raise pyodbc.Error("08S01", "error privado")
        return original(sql)

    monkeypatch.setattr(cursor, "execute", ejecutar)
    monkeypatch.setattr(driver, "cursor", lambda: cursor)
    with sesion_sql_acotada(conn):
        driver.nocount = True
    assert conn.invalidated is True
    conn.invalidate.assert_called_once()
    conn.commit.assert_not_called()


def test_error_rollback_no_oculta_original_y_descarta(conexion):
    conn, driver = conexion
    conn.rollback.side_effect = SQLAlchemyError("rollback fallido")
    with (
        pytest.raises(SQLAlchemyError, match="error original"),
        sesion_sql_acotada(conn),
    ):
        driver.nocount = True
        raise SQLAlchemyError("error original")
    assert conn.invalidated is True


def test_error_preparacion_impide_ejecutar_operacion(conexion, monkeypatch):
    conn, driver = conexion
    monkeypatch.setattr(
        driver, "cursor", MagicMock(side_effect=pyodbc.Error("08S01", "SECRETO"))
    )
    operacion = MagicMock()
    with pytest.raises(SQLAlchemyError) as error, sesion_sql_acotada(conn):
        operacion()
    assert "SECRETO" not in str(error.value)
    assert conn.invalidated is True
    operacion.assert_not_called()
