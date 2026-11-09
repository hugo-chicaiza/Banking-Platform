"""Errores y límites de asignación de PIN, exclusivamente con conexiones dobles."""

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock

import pyodbc
import pytest
from fastapi import HTTPException
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from app.modules.tarjetas import service
from app.modules.tarjetas.pin_sql import limitar_sql_pin
from tests.pin_version import DriverLimitesSQL


@pytest.fixture
def lab(monkeypatch):
    conn = MagicMock()
    driver = DriverLimitesSQL()
    conn.connection.driver_connection = driver
    conn.invalidated = False
    hsm = MagicMock()
    hsm.generar_pin.return_value = ("0042", "LAB-PVK")
    monkeypatch.setattr(service, "pan_de_prueba", MagicMock(return_value="PAN-LAB"))
    save = MagicMock()
    monkeypatch.setattr(service.repository, "guardar_pin_generado", save)
    return SimpleNamespace(conn=conn, driver=driver, hsm=hsm, save=save)


@pytest.mark.parametrize("query,lock", [(0, -1), (3, 100), (30, 20000), (0, 0)])
def test_limites_temporales_respetan_previos_y_se_restauran(lab, query, lock):
    lab.driver.timeout, lab.driver.lock_timeout = query, lock
    with limitar_sql_pin(lab.conn):
        assert lab.driver.timeout == (min(query, 15) if query > 0 else 15)
        assert lab.driver.lock_timeout == (min(lock, 5000) if lock >= 0 else 5000)
    assert (lab.driver.timeout, lab.driver.lock_timeout) == (query, lock)
    lab.conn.commit.assert_not_called()


@pytest.mark.parametrize(
    "state,native", [("HYT00", 0), ("40001", 1205), ("HY000", 1222), ("08S01", 0)]
)
def test_timeout_deadlock_desconexion_503_sin_reintento(lab, state, native, caplog):
    lab.save.side_effect = DBAPIError(
        "UPDATE SECRETO",
        {"offset": "SECRETO"},
        pyodbc.Error(state, f"SECRETO ({native}) (SQLExecDirectW)"),
    )
    with pytest.raises(HTTPException) as error:
        service._generar_pin(lab.conn, 301, "Debito", lab.hsm, "Regeneracion")
    assert error.value.status_code == 503
    assert isinstance(error.value.detail, dict)
    assert (
        cast(dict[str, Any], error.value.detail)["code"]
        == "PIN_ASIGNACION_NO_CONFIRMADA"
    )
    assert "SECRETO" not in str(error.value.detail) + caplog.text
    lab.save.assert_called_once()
    lab.conn.rollback.assert_called_once()
    lab.conn.commit.assert_not_called()
    assert (lab.driver.timeout, lab.driver.lock_timeout) == (0, -1)


def test_error_negocio_conserva_respuesta(lab):
    lab.save.side_effect = DBAPIError(
        "lab", {}, pyodbc.Error("42000", "regla (52005) (SQLExecDirectW)")
    )
    with pytest.raises(HTTPException) as error:
        service._generar_pin(lab.conn, 301, "Credito", lab.hsm, "Regeneracion")
    assert error.value.status_code == 409
    assert isinstance(error.value.detail, dict)
    assert cast(dict[str, Any], error.value.detail)["code"] == "TRANSICION_INVALIDA"
    lab.conn.commit.assert_not_called()


def test_commit_ambiguo_no_afirma_resultado_ni_reintenta(lab):
    lab.conn.commit.side_effect = DBAPIError(
        "COMMIT", {}, pyodbc.Error("08S01", "SECRETO")
    )
    with pytest.raises(HTTPException) as error:
        service._generar_pin(lab.conn, 301, "Credito", lab.hsm, "Regeneracion")
    assert error.value.status_code == 503
    assert (
        "Requiere reconciliación" in cast(dict[str, Any], error.value.detail)["message"]
    )
    assert "SECRETO" not in str(error.value.detail)
    lab.save.assert_called_once()
    lab.conn.commit.assert_called_once()
    lab.conn.rollback.assert_called_once()


def test_rollback_fallido_no_oculta_error_y_descarta_conexion(lab):
    lab.save.side_effect = SQLAlchemyError("SECRETO")
    lab.conn.rollback.side_effect = SQLAlchemyError("SECRETO-ROLLBACK")
    with pytest.raises(HTTPException) as error:
        service._generar_pin(lab.conn, 301, "Credito", lab.hsm, "Regeneracion")
    assert error.value.status_code == 503
    assert "SECRETO" not in str(error.value.detail)
    lab.conn.invalidate.assert_called_once()
    lab.conn.commit.assert_not_called()


def test_fallo_configurar_limites_impide_asignacion(lab, monkeypatch):
    monkeypatch.setattr(
        lab.driver, "cursor", MagicMock(side_effect=pyodbc.Error("08S01", "lab"))
    )
    with pytest.raises(HTTPException) as error:
        service._generar_pin(lab.conn, 301, "Credito", lab.hsm, "Regeneracion")
    assert error.value.status_code == 503
    lab.save.assert_not_called()
    lab.conn.commit.assert_not_called()
    lab.conn.invalidate.assert_called()


def test_fallo_restaurar_descarta_conexion_sin_repetir_commit(lab, monkeypatch):
    cursor = lab.driver.cursor()
    monkeypatch.setattr(
        lab.driver,
        "cursor",
        MagicMock(side_effect=[cursor, pyodbc.Error("08S01", "lab")]),
    )
    service._generar_pin(lab.conn, 301, "Credito", lab.hsm, "Regeneracion")
    lab.conn.commit.assert_called_once()
    lab.save.assert_called_once()
    lab.conn.invalidate.assert_called_once()


def test_rollback_de_ambas_conexiones_aunque_la_primera_falle(lab):
    coop = MagicMock()
    lab.conn.rollback.side_effect = SQLAlchemyError("lab")
    service._rollback(lab.conn, coop)
    lab.conn.invalidate.assert_called_once()
    coop.rollback.assert_called_once()
