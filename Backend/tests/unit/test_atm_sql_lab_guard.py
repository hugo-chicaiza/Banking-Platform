"""Límites del laboratorio con dobles; nunca se conectan bases reales."""

from unittest.mock import MagicMock

import pytest

from tests.integration import atm_saldo_sql_lab as lab


@pytest.mark.parametrize(
    "database", ["CatBank", "PetroleumDW", "CooperativaDB", "SeguridadDB", "master"]
)
def test_conexion_fuera_del_laboratorio_no_llega_al_driver(monkeypatch, database):
    conectar = MagicMock()
    monkeypatch.setattr(lab.pyodbc, "connect", conectar)
    with pytest.raises(RuntimeError):
        lab.conectar(database)
    conectar.assert_not_called()


@pytest.mark.parametrize(
    "sql",
    [
        "USE CatBank",
        "DELETE FROM CatBank.dbo.Cuenta",
        "DELETE FROM [CatBank].[dbo].[Cuenta]",
        "UPDATE PetroleumDW.dbo.X SET a=1",
        "INSERT INTO CooperativaDB.Cuentas.Cuenta VALUES (1)",
        "DROP DATABASE SeguridadDB_ATM02_Lab",
        "SELECT * FROM OPENQUERY(otro,'SELECT 1')",
    ],
)
@pytest.mark.parametrize("many", [False, True])
def test_sql_fuera_de_alcance_no_se_ejecuta(monkeypatch, sql, many):
    monkeypatch.setattr(lab, "verificar", MagicMock())
    raw, cursor = MagicMock(), MagicMock()
    protegido = lab.CursorLocal(raw, cursor, lab.COOP)
    with pytest.raises(RuntimeError):
        if many:
            protegido.executemany(sql, [(1,)])
        else:
            protegido.execute(sql)
    cursor.execute.assert_not_called()
    cursor.executemany.assert_not_called()


@pytest.mark.parametrize(
    "modificacion",
    [
        (0, "otro-servidor"),
        (1, "otra-maquina"),
        (2, "SQLEXPRESS"),
        (3, 5),
        (4, "CatBank"),
    ],
)
def test_identidad_sql_inesperada_se_rechaza(modificacion):
    raw = MagicMock()
    row = [lab.SERVER, lab.SERVER, None, 2, lab.COOP]
    row[modificacion[0]] = modificacion[1]
    raw.cursor.return_value.execute.return_value.fetchone.return_value = tuple(row)
    with pytest.raises(RuntimeError):
        lab.verificar(raw, lab.COOP)


def test_marca_de_laboratorio_obligatoria():
    raw = MagicMock()
    raw.cursor.return_value.execute.return_value.fetchone.return_value = (
        lab.SERVER,
        lab.SERVER,
        None,
        2,
        lab.COOP,
    )
    raw.cursor.return_value.execute.return_value.fetchval.return_value = None
    with pytest.raises(RuntimeError):
        lab.verificar(raw, lab.COOP)


def test_commit_verifica_destino_antes_de_escribir(monkeypatch):
    raw = MagicMock()
    monkeypatch.setattr(
        lab, "verificar", MagicMock(side_effect=RuntimeError("Destino inesperado"))
    )
    with pytest.raises(RuntimeError):
        lab.ConexionLocal(raw, lab.COOP).commit()
    raw.commit.assert_not_called()
