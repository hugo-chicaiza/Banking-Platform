"""Protecciones para que el laboratorio no escriba en bases compartidas."""

from unittest.mock import MagicMock

import pytest

from tests.integration import ac02_sql_lab as lab


@pytest.mark.parametrize("database", ["CooperativaDB", "SeguridadDB", "master"])
def test_destino_ajeno_no_llega_al_driver(monkeypatch, database):
    monkeypatch.setenv("AC02_LOCAL_SQL_ENABLED", "1")
    driver = MagicMock()
    monkeypatch.setattr(lab.pyodbc, "connect", driver)
    with pytest.raises(RuntimeError):
        lab.conectar(database)
    driver.assert_not_called()


def test_laboratorio_requiere_activacion_explicita(monkeypatch):
    monkeypatch.delenv("AC02_LOCAL_SQL_ENABLED", raising=False)
    driver = MagicMock()
    monkeypatch.setattr(lab.pyodbc, "connect", driver)
    with pytest.raises(RuntimeError):
        lab.conectar()
    driver.assert_not_called()


@pytest.mark.parametrize(
    "identidad", [(0, 4, lab.DATABASE), (0, 5, lab.DATABASE), (1, 4, "CooperativaDB")]
)
def test_identidad_no_local_o_base_distinta_se_rechaza(identidad):
    conn = MagicMock()
    conn.cursor.return_value.execute.return_value.fetchone.return_value = identidad
    with pytest.raises(RuntimeError):
        lab.verificar(conn, lab.DATABASE)


def test_base_sin_marca_se_rechaza():
    conn = MagicMock()
    cursor = conn.cursor.return_value
    cursor.execute.return_value.fetchone.return_value = (1, 4, lab.DATABASE)
    cursor.execute.return_value.fetchval.return_value = None
    with pytest.raises(RuntimeError):
        lab.verificar(conn, lab.DATABASE)
