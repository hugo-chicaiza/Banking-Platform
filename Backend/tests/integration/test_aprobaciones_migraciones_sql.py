"""DDL y rollback solo en SQL local propio, nunca en bases compartidas."""

import os
from pathlib import Path
from uuid import uuid4

import pyodbc
import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("E008_LOCAL_MANIFEST"),
    reason="Laboratorio local E0-08 requerido",
)


def test_fallo_instalacion_revierte_trigger_y_detalle_sin_tocar_legacy():
    nombre = "BankingE008_Rollback_" + uuid4().hex
    cadena = "DRIVER={ODBC Driver 18 for SQL Server};SERVER=lpc:.;Trusted_Connection=yes;Encrypt=no;DATABASE="
    with pyodbc.connect(cadena + "master", autocommit=True) as master:
        assert (
            master.execute(
                "SELECT CONVERT(int,SERVERPROPERTY('EngineEdition'))"
            ).fetchval()
            != 5
        )
        master.execute(f"CREATE DATABASE [{nombre}]")
        try:
            with pyodbc.connect(cadena + nombre, autocommit=True) as c:
                assert c.execute("SELECT DB_NAME()").fetchval() == nombre
                c.execute("CREATE SCHEMA Auditoria")
                c.execute(
                    "CREATE TABLE Auditoria.Auditoria(AuditoriaID int IDENTITY PRIMARY KEY,Descripcion varchar(500)); INSERT Auditoria.Auditoria VALUES('Registro previo legitimo');"
                )
                c.execute(
                    "EXEC sys.sp_set_session_context @key=N'migration_database',@value=?",
                    nombre,
                )
                script = (
                    Path(__file__).parents[2]
                    / "migrations/seguridad/202611180803_aprobaciones_auditoria.up.sql"
                ).read_text(encoding="utf-8")
                assert script.count(" COMMIT TRANSACTION;") == 1
                fallido = script.replace(
                    " COMMIT TRANSACTION;",
                    " THROW 57399,'Fallo de ensayo local previo al commit.',1; COMMIT TRANSACTION;",
                )
                with pytest.raises(pyodbc.Error, match="57399"):
                    c.execute(fallido)
                assert (
                    c.execute("SELECT OBJECT_ID('Auditoria.EventoDetalle')").fetchval()
                    is None
                )
                assert (
                    c.execute(
                        "SELECT OBJECT_ID('Auditoria.trg_Auditoria_E008_Protegida')"
                    ).fetchval()
                    is None
                )
                assert (
                    c.execute("SELECT Descripcion FROM Auditoria.Auditoria").fetchval()
                    == "Registro previo legitimo"
                )
                # Una tabla parcial propia nunca se adopta como una instalacion valida.
                c.execute("CREATE TABLE Auditoria.EventoDetalle(Id int)")
                with pytest.raises(pyodbc.Error, match="57390"):
                    c.execute(script)
                assert (
                    c.execute(
                        "SELECT COL_LENGTH('Auditoria.EventoDetalle','Id')"
                    ).fetchval()
                    == 4
                )
                assert (
                    c.execute(
                        "SELECT OBJECT_ID('Auditoria.trg_Auditoria_E008_Protegida')"
                    ).fetchval()
                    is None
                )
                # Solo esta tabla creada por el ensayo en esta base local UUID.
                assert c.execute("SELECT DB_NAME()").fetchval() == nombre
                c.execute("DROP TABLE Auditoria.EventoDetalle")
                for _ in range(2):
                    cursor = c.execute(script)
                    while cursor.nextset():
                        pass
                assert (
                    c.execute("SELECT COUNT(*) FROM Auditoria.Auditoria").fetchval()
                    == 1
                )
                assert (
                    c.execute("SELECT COUNT(*) FROM Auditoria.EventoDetalle").fetchval()
                    == 0
                )
                c.execute(
                    "UPDATE Auditoria.Auditoria SET Descripcion='Actualizacion legacy valida'; INSERT Auditoria.Auditoria VALUES('Otro modulo legitimo');"
                )
                assert (
                    c.execute("SELECT COUNT(*) FROM Auditoria.Auditoria").fetchval()
                    == 2
                )
        finally:
            assert (
                nombre.startswith("BankingE008_Rollback_")
                and len(nombre) == len("BankingE008_Rollback_") + 32
            )
            master.execute(
                f"ALTER DATABASE [{nombre}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE"
            )
            master.execute(f"DROP DATABASE [{nombre}]")
