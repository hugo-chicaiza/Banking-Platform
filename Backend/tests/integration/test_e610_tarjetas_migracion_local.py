"""Ensayo optativo de E6-10 en una base descartable de SQL Server LocalDB."""

import os
from pathlib import Path
from uuid import uuid4

import pyodbc
import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("E610_LOCALDB") != "1", reason="Requiere SQL Server LocalDB"
)

_BACKEND = Path(__file__).resolve().parents[2]
_RAIZ = _BACKEND / "migrations" / "cooperativa"
_MIGRACION = "202611251600_tarjetas_debito"


def test_e610_esquema_y_retiro_credito():
    base = "LabE610_" + uuid4().hex
    with pyodbc.connect(
        r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=(localdb)\MSSQLLocalDB;"
        "DATABASE=master;Trusted_Connection=yes;Encrypt=no;Connection Timeout=5;",
        autocommit=True,
    ) as conn:
        cur = conn.cursor()
        cur.execute(f"CREATE DATABASE [{base}]")
        try:
            cur.execute(f"USE [{base}]")
            for esquema in ("Catalogo", "Tarjeta", "ProductosFinancieros", "Canal"):
                cur.execute(f"CREATE SCHEMA [{esquema}]")
            cur.execute("""
                CREATE TABLE Tarjeta.Tarjeta (
                    IdTarjeta int PRIMARY KEY, IdSubProducto int, Estado varchar(20),
                    FechaResolucion datetime2 NULL
                );
                CREATE TABLE Tarjeta.EnviosTarjeta (IdTarjeta int PRIMARY KEY);
                CREATE TABLE ProductosFinancieros.SubProducto (
                    IdSubProducto int PRIMARY KEY, CodigoSubProducto varchar(30),
                    Estado char(1), EstadoSubProducto varchar(20)
                );
                CREATE TABLE Tarjeta.TransicionEstado (
                    EstadoOrigen varchar(20), EstadoDestino varchar(20)
                );
                CREATE TABLE Tarjeta.TarjetaHis (
                    IdTarjeta int, TipoEvento varchar(20), EstadoAnterior varchar(20),
                    EstadoActual varchar(20), Descripcion nvarchar(500),
                    IdCanal int, RealizadoPor int
                );
                CREATE TABLE Canal.Canal (IdCanal int, CodigoCanal varchar(10));
                INSERT Canal.Canal VALUES (1, 'VENT');
                INSERT ProductosFinancieros.SubProducto VALUES
                    (1, 'TCR001-MC', 'A', 'Activo'), (2, 'TDB001-MC', 'A', 'Activo');
                INSERT Tarjeta.Tarjeta VALUES (1, 1, 'Solicitada', NULL), (2, 2, 'Activa', NULL);
                INSERT Tarjeta.TransicionEstado VALUES ('Solicitada', 'Anulada');
            """)
            cur.execute(
                "EXEC sys.sp_set_session_context N'migration_database', ?", base
            )
            cur.execute("EXEC sys.sp_set_session_context N'migration_actor_id', 17")
            up = (_RAIZ / f"{_MIGRACION}.up.sql").read_text(encoding="utf-8")
            down = (_RAIZ / f"{_MIGRACION}.down.sql").read_text(encoding="utf-8")
            corte = (_BACKEND / "scripts/sql/e610/retirar_credito.sql").read_text(
                encoding="utf-8"
            )
            cur.execute(up)
            cur.execute(up)
            cur.execute(down)
            assert (
                cur.execute(
                    "SELECT COL_LENGTH('Tarjeta.Tarjeta', 'MotivoEstado')"
                ).fetchval()
                is None
            )
            cur.execute(up)
            cur.execute(corte)
            cur.execute(corte)
            tarjeta = cur.execute(
                "SELECT Estado, MotivoEstado, FechaResolucion FROM Tarjeta.Tarjeta WHERE IdTarjeta=1"
            ).fetchone()
            assert tarjeta is not None
            assert tuple(tarjeta[:2]) == ("Anulada", "PRODUCTO_SUSPENDIDO")
            assert tarjeta[2] is not None
            assert (
                cur.execute("SELECT COUNT(*) FROM Tarjeta.TarjetaHis").fetchval() == 1
            )
            assert (
                cur.execute(
                    "SELECT EstadoSubProducto FROM ProductosFinancieros.SubProducto WHERE IdSubProducto=1"
                ).fetchval()
                == "Suspendido"
            )
            assert (
                cur.execute(
                    "SELECT Estado FROM Tarjeta.Tarjeta WHERE IdTarjeta=2"
                ).fetchval()
                == "Activa"
            )
            with pytest.raises(pyodbc.Error, match="57711"):
                cur.execute(down)
        finally:
            cur.execute("IF @@TRANCOUNT > 0 ROLLBACK; USE [master];")
            cur.execute(f"DROP DATABASE [{base}]")
