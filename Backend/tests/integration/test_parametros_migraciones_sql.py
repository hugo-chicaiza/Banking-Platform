"""Ensayos DDL destructivos exclusivamente en bases locales nuevas de este test."""

import os
from pathlib import Path
from uuid import uuid4

import pyodbc
import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("E009_LOCAL_DDL") != "1", reason="DDL opt-in solo SQL Server local"
)


@pytest.fixture
def laboratorio():
    nombre = "BankingE009_Migracion_" + uuid4().hex
    cadena = "DRIVER={ODBC Driver 18 for SQL Server};SERVER=lpc:.;Trusted_Connection=yes;Encrypt=no;"
    with pyodbc.connect(cadena + "DATABASE=master", autocommit=True) as admin:
        servidor = admin.execute(
            "SELECT CONVERT(varchar(128),SERVERPROPERTY('ServerName')),CONVERT(int,SERVERPROPERTY('EngineEdition'))"
        ).fetchone()
        assert servidor is not None and servidor[1] != 5
        admin.execute(f"CREATE DATABASE [{nombre}]")
        try:
            with pyodbc.connect(cadena + "DATABASE=" + nombre, autocommit=True) as conn:
                assert conn.execute("SELECT DB_NAME()").fetchval() == nombre
                conn.execute("CREATE SCHEMA Organizacion")
                conn.execute(
                    "CREATE TABLE Organizacion.Agencia(IdAgencia char(3) NOT NULL PRIMARY KEY,Estado char(1));"
                )
                conn.execute(
                    "EXEC sys.sp_set_session_context @key=N'migration_database',@value=?",
                    nombre,
                )
                yield conn
        finally:
            # Solo la base generada aqui, nunca un nombre externo de configuracion.
            assert (
                nombre.startswith("BankingE009_Migracion_")
                and len(nombre) == len("BankingE009_Migracion_") + 32
            )
            admin.execute(
                f"ALTER DATABASE [{nombre}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE"
            )
            admin.execute(f"DROP DATABASE [{nombre}]")


def sql(nombre: str) -> str:
    return (Path(__file__).parents[2] / "migrations/cooperativa" / nombre).read_text(
        encoding="utf-8"
    )


def test_migracion_y_semillas_repetibles(laboratorio):
    estructura = sql("202611172000_parametros_estructura.up.sql")
    semillas = sql("202611172001_parametros_semillas.up.sql")
    for _ in range(2):
        laboratorio.execute(estructura)
        laboratorio.execute(semillas)
    assert (
        laboratorio.execute("SELECT COUNT(*) FROM Parametros.Parametro").fetchval() == 7
    )
    assert (
        laboratorio.execute("SELECT COUNT(*) FROM Parametros.ParametroValor").fetchval()
        == 7
    )


def test_fallo_antes_commit_revierte_toda_estructura(laboratorio):
    contenido = sql("202611172000_parametros_estructura.up.sql")
    assert " COMMIT TRANSACTION;" in contenido
    contenido = contenido.replace(
        " COMMIT TRANSACTION;",
        " THROW 57199,'Fallo controlado del ensayo local.',1; COMMIT TRANSACTION;",
    )
    with pytest.raises(pyodbc.Error, match="57199"):
        laboratorio.execute(contenido)
    assert tuple(
        laboratorio.execute(
            "SELECT OBJECT_ID('Parametros.Parametro'),SCHEMA_ID('Parametros')"
        ).fetchone()
    ) == (None, None)
    assert (
        laboratorio.execute("SELECT OBJECT_ID('Organizacion.Agencia')").fetchval()
        is not None
    )


def test_instalacion_parcial_no_es_sobrescrita(laboratorio):
    laboratorio.execute("CREATE SCHEMA Parametros")
    laboratorio.execute("CREATE TABLE Parametros.Parametro(Id int NOT NULL)")
    with pytest.raises(pyodbc.Error, match="57190"):
        laboratorio.execute(sql("202611172000_parametros_estructura.up.sql"))
    assert (
        laboratorio.execute("SELECT COL_LENGTH('Parametros.Parametro','Id')").fetchval()
        == 4
    )
    assert (
        laboratorio.execute("SELECT OBJECT_ID('Parametros.ParametroValor')").fetchval()
        is None
    )


def test_semilla_hora_referencia_no_modifica_calendario(laboratorio):
    laboratorio.execute(sql("202611172000_parametros_estructura.up.sql"))
    laboratorio.execute("CREATE SCHEMA Contabilidad")
    laboratorio.execute(
        "CREATE TABLE Contabilidad.FechaContable(Fecha date PRIMARY KEY,HoraCorte time(7) NULL)"
    )
    laboratorio.execute(
        "INSERT Contabilidad.FechaContable VALUES(CONVERT(date,SWITCHOFFSET(SYSDATETIMEOFFSET(),'-05:00')),'19:00:00')"
    )
    antes = [
        tuple(r)
        for r in laboratorio.execute(
            "SELECT Fecha,HoraCorte FROM Contabilidad.FechaContable"
        ).fetchall()
    ]
    for _ in range(2):
        laboratorio.execute(sql("202611172002_parametros_hora_corte.up.sql"))
    fila = laboratorio.execute(
        "SELECT p.Estado,v.Valor FROM Parametros.Parametro p JOIN Parametros.ParametroValor v ON v.IdParametro=p.IdParametro WHERE p.Clave='CON_HORA_CORTE'"
    ).fetchone()
    assert tuple(fila) == ("I", "19:00")
    despues = [
        tuple(r)
        for r in laboratorio.execute(
            "SELECT Fecha,HoraCorte FROM Contabilidad.FechaContable"
        ).fetchall()
    ]
    assert antes == despues


def test_hora_corte_no_se_redondea_silenciosamente(laboratorio):
    laboratorio.execute(sql("202611172000_parametros_estructura.up.sql"))
    laboratorio.execute("CREATE SCHEMA Contabilidad")
    laboratorio.execute(
        "CREATE TABLE Contabilidad.FechaContable(Fecha date PRIMARY KEY,HoraCorte time(7) NULL)"
    )
    laboratorio.execute(
        "INSERT Contabilidad.FechaContable VALUES(CONVERT(date,SWITCHOFFSET(SYSDATETIMEOFFSET(),'-05:00')),'19:00:30')"
    )
    with pytest.raises(pyodbc.Error, match="57190"):
        laboratorio.execute(sql("202611172002_parametros_hora_corte.up.sql"))
    assert (
        laboratorio.execute(
            "SELECT COUNT(*) FROM Parametros.Parametro WHERE Clave='CON_HORA_CORTE'"
        ).fetchval()
        == 0
    )
