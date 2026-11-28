"""E5-02: política de correo sobre SQL Server LocalDB desechable."""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from threading import Barrier
from typing import cast
from uuid import uuid4

import pyodbc
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from app.core.api.errors import traducir_error_bd
from app.core.migraciones.archivos import lotes
from app.modules.clientes.correo_principal import validar_dominio

pytestmark = pytest.mark.skipif(
    os.getenv("E539_CORREO_SQL_LOCAL") != "1", reason="Requiere SQL Server LocalDB"
)
DSN = (
    r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=(localdb)\EnquoAccesosQA;"
    "Trusted_Connection=yes;Encrypt=no;DATABASE="
)
MIGRACIONES = Path(__file__).resolve().parents[2] / "migrations/cooperativa"
BASE = "202611281030_clientes_correo_principal"
FECHA = date(2026, 11, 28)


def migrar(conn, archivo):
    conn.exec_driver_sql(
        "DECLARE @destino sysname = DB_NAME(); "
        "EXEC sys.sp_set_session_context N'migration_database', @destino;"
    )
    for lote in lotes((MIGRACIONES / archivo).read_text(encoding="utf-8")):
        conn.exec_driver_sql(lote)


@pytest.fixture
def bd():
    nombre = "E539Correo_" + uuid4().hex
    admin = create_engine(
        "mssql+pyodbc://",
        creator=lambda: pyodbc.connect(DSN + "master", autocommit=True, timeout=5),
        isolation_level="AUTOCOMMIT",
    )
    with admin.connect() as conn:
        conn.exec_driver_sql(f"CREATE DATABASE [{nombre}]")
    motor = create_engine(
        "mssql+pyodbc://",
        creator=lambda: pyodbc.connect(DSN + nombre, timeout=5),
        hide_parameters=True,
    )
    try:
        with motor.begin() as conn:
            for esquema in ("Clientes", "Organizacion"):
                conn.exec_driver_sql(f"CREATE SCHEMA {esquema}")
            conn.exec_driver_sql("""
                CREATE TABLE Organizacion.Agencia(IdAgencia char(3) PRIMARY KEY);
                CREATE TABLE Clientes.Cliente(
                    IdCliente int IDENTITY PRIMARY KEY,
                    Email varchar(150) COLLATE Latin1_General_100_CS_AS NULL
                );
            """)
            migrar(conn, "202611172000_parametros_estructura.up.sql")
        yield motor
    finally:
        motor.dispose()
        try:
            with admin.connect() as conn:
                conn.exec_driver_sql(
                    f"ALTER DATABASE [{nombre}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE;"
                    f"DROP DATABASE [{nombre}];"
                )
        finally:
            admin.dispose()


def test_indice_protege_altas_simultaneas_y_edicion(bd):
    with bd.begin() as conn:
        migrar(conn, f"{BASE}.up.sql")
    barrera = Barrier(2)

    def alta(email):
        barrera.wait(timeout=10)
        try:
            with bd.begin() as conn:
                conn.execute(
                    text("INSERT Clientes.Cliente(Email) VALUES(:email)"),
                    {"email": email},
                )
            return 201, None
        except DBAPIError as error:
            problema = traducir_error_bd(error)
            detalle = cast(dict[str, str], problema.detail)
            return problema.status_code, detalle["code"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        resultados = list(
            pool.map(alta, [" NOMBRE@ejemplo.test ", "nombre@ejemplo.test"])
        )
    assert sorted(resultados) == [(201, None), (409, "EMAIL_DUPLICADO")]
    with bd.begin() as conn:
        assert (
            conn.exec_driver_sql("SELECT COUNT(*) FROM Clientes.Cliente").scalar_one()
            == 1
        )
        conn.exec_driver_sql(
            "INSERT Clientes.Cliente(Email) VALUES('otro@ejemplo.test')"
        )
    with pytest.raises(DBAPIError) as conflicto, bd.begin() as conn:
        conn.exec_driver_sql(
            "UPDATE Clientes.Cliente SET Email='NOMBRE@EJEMPLO.TEST' WHERE Email='otro@ejemplo.test'"
        )
    detalle = cast(dict[str, str], traducir_error_bd(conflicto.value).detail)
    assert detalle["code"] == "EMAIL_DUPLICADO"


def test_dominios_globales_y_reversion_sin_perder_configuracion(bd):
    with bd.begin() as conn:
        migrar(conn, f"{BASE}.up.sql")
        validar_dominio(conn, "persona@bloqueado.test", FECHA)
        conn.exec_driver_sql("""
            UPDATE v SET Valor=N'[" BLOQUEADO.TEST "]'
            FROM Parametros.ParametroValor v
            JOIN Parametros.Parametro p ON p.IdParametro=v.IdParametro
            WHERE p.Clave='CLI_DOMINIOS_BLOQUEADOS';
        """)
        with pytest.raises(HTTPException) as bloqueado:
            validar_dominio(conn, "persona@bloqueado.test", FECHA)
        detalle = cast(dict[str, str], bloqueado.value.detail)
        assert (bloqueado.value.status_code, detalle["code"]) == (
            422,
            "DOMINIO_BLOQUEADO",
        )
        validar_dominio(conn, "persona@sub.bloqueado.test", FECHA)
        migrar(conn, f"{BASE}.down.sql")
        assert (
            conn.exec_driver_sql(
                "SELECT COL_LENGTH('Clientes.Cliente', 'EmailPrincipalNormalizado')"
            ).scalar_one()
            is None
        )
        with pytest.raises(HTTPException):
            validar_dominio(conn, "persona@bloqueado.test", FECHA)


def test_migracion_aborta_si_hay_duplicados_historicos(bd):
    with bd.begin() as conn:
        conn.exec_driver_sql(
            "INSERT Clientes.Cliente(Email) VALUES(' Repetido@ejemplo.test '), ('repetido@ejemplo.test')"
        )
    with (
        pytest.raises(DBAPIError, match="Hay correos principales repetidos"),
        bd.begin() as conn,
    ):
        migrar(conn, f"{BASE}.up.sql")
    with bd.connect() as conn:
        assert (
            conn.exec_driver_sql("SELECT COUNT(*) FROM Clientes.Cliente").scalar_one()
            == 2
        )
        assert (
            conn.exec_driver_sql(
                "SELECT COL_LENGTH('Clientes.Cliente', 'EmailPrincipalNormalizado')"
            ).scalar_one()
            is None
        )
