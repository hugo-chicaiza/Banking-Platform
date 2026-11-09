"""Laboratorio mínimo AC-02: solo LocalDB, sin .env ni credenciales de Azure."""

import argparse
import json
import os
from contextlib import closing
from datetime import date
from pathlib import Path

import pyodbc

SERVER = r"(localdb)\MSSQLLocalDB"
DATABASE = "CooperativaDB_AC02_Lab"
MARKER = "Banking-Platform.AC02.Local.Fictional.v1"
SQL_DIR = Path(__file__).resolve().parents[2] / "scripts/sql/ac02"


def verificar(conn, database: str, *, marker: bool = True) -> None:
    with closing(conn.cursor()) as cur:
        fila = cur.execute("""
            SELECT CONVERT(int, SERVERPROPERTY('IsLocalDB')),
                   CONVERT(int, SERVERPROPERTY('EngineEdition')), DB_NAME()
        """).fetchone()
        if (
            database not in (DATABASE, "master")
            or fila is None
            or fila[0] != 1
            or fila[1] != 4
            or fila[2] != database
        ):
            raise RuntimeError("Destino fuera del laboratorio LocalDB de AC-02")
        if marker:
            valor = cur.execute("""
                SELECT CONVERT(nvarchar(128), value) FROM sys.extended_properties
                WHERE class=0 AND name='AC02_Lab'
            """).fetchval()
            if database != DATABASE or valor != MARKER:
                raise RuntimeError("Base sin marca del laboratorio AC-02")


def conectar(database: str = DATABASE, *, bootstrap: bool = False):
    if os.environ.get("AC02_LOCAL_SQL_ENABLED") != "1":
        raise RuntimeError("Laboratorio AC-02 local deshabilitado")
    if database != DATABASE and not (database == "master" and bootstrap):
        raise RuntimeError("Base fuera del laboratorio AC-02")
    conn = pyodbc.connect(
        "DRIVER={ODBC Driver 18 for SQL Server};"
        f"SERVER={SERVER};DATABASE={database};Trusted_Connection=yes;"
        "Encrypt=yes;TrustServerCertificate=yes;APP=AC02_Local_Lab;",
        autocommit=True,
        timeout=10,
    )
    conn.timeout = 15
    try:
        verificar(conn, database, marker=not bootstrap)
    except BaseException:
        conn.close()
        raise
    return conn


def crear() -> None:
    with (
        closing(conectar("master", bootstrap=True)) as conn,
        closing(conn.cursor()) as cur,
    ):
        if cur.execute(
            "SELECT name FROM sys.databases WHERE name=?", DATABASE
        ).fetchone():
            raise RuntimeError("El laboratorio ya existe; no se sobrescribe")
        verificar(conn, "master", marker=False)
        cur.execute("CREATE DATABASE [CooperativaDB_AC02_Lab]")

    with (
        closing(conectar(DATABASE, bootstrap=True)) as conn,
        closing(conn.cursor()) as cur,
    ):
        verificar(conn, DATABASE, marker=False)
        cur.execute(
            "EXEC sys.sp_addextendedproperty @name=N'AC02_Lab', @value=?",
            MARKER,
        )
        verificar(conn, DATABASE)
        cur.execute("CREATE SCHEMA Contabilidad")
        verificar(conn, DATABASE)
        cur.execute("""
            CREATE TABLE Contabilidad.FechaContable (
                IdFechaContable int NOT NULL PRIMARY KEY,
                Fecha date NOT NULL UNIQUE,
                EsDiaContable bit NOT NULL,
                EsFeriado bit NOT NULL,
                EsFinDeSemana bit NOT NULL,
                HoraCorte time(0) NOT NULL
            )
        """)
        # Fixture mínimo: no copia clientes, cuentas ni registros de Azure.
        dias = [date(2026, 1, d) for d in range(1, 6)] + [
            date(2026, 11, d) for d in range(6, 11)
        ]
        filas = []
        for dia in dias:
            feriado = dia == date(2026, 1, 1)
            fin_semana = dia.weekday() >= 5
            filas.append(
                (
                    int(dia.strftime("%Y%m%d")),
                    dia,
                    not feriado and not fin_semana,
                    feriado,
                    fin_semana,
                    "19:00:00",
                )
            )
        verificar(conn, DATABASE)
        cur.executemany(
            "INSERT INTO Contabilidad.FechaContable "
            "(IdFechaContable,Fecha,EsDiaContable,EsFeriado,EsFinDeSemana,HoraCorte) "
            "VALUES (?,?,?,?,?,?)",
            filas,
        )
        original = (SQL_DIR / "001_corte_precision.down.sql").read_text(
            encoding="utf-8"
        )
        verificar(conn, DATABASE)
        cur.execute(original.replace("ALTER FUNCTION", "CREATE FUNCTION", 1))


def resultados(conn) -> list[dict]:
    verificar(conn, DATABASE)
    with closing(conn.cursor()) as cur:
        cur.execute((SQL_DIR / "validar_corte.sql").read_text(encoding="utf-8"))
        columnas = [d[0] for d in cur.description]
        return [dict(zip(columnas, f)) for f in cur.fetchall()]


def ciclo() -> list[dict]:
    informe = []
    referencia_original = None
    with closing(conectar()) as conn:
        for etapa, archivo, esperados in (
            # Se restablece la versión antigua solo en el laboratorio marcado,
            # para permitir repetir el ciclo aunque termine con la corregida.
            ("original", "001_corte_precision.down.sql", 10),
            ("corregida", "001_corte_precision.up.sql", 13),
            ("revertida", "001_corte_precision.down.sql", 10),
            ("corregida_final", "001_corte_precision.up.sql", 13),
        ):
            if archivo:
                verificar(conn, DATABASE)
                with closing(conn.cursor()) as cur:
                    cur.execute((SQL_DIR / archivo).read_text(encoding="utf-8"))
            filas = resultados(conn)
            actuales = sum(f["EstadoActual"] == "OK" for f in filas)
            propuestos = sum(f["EstadoPropuesta"] == "OK" for f in filas)
            if len(filas) != 13 or actuales != esperados or propuestos != 13:
                raise AssertionError(f"Resultado inesperado en {etapa}: {filas}")
            resultados_instalados = {f["Instante"]: f["ResultadoActual"] for f in filas}
            if etapa == "original":
                referencia_original = resultados_instalados
            elif etapa == "revertida" and resultados_instalados != referencia_original:
                raise AssertionError("La reversión no restauró los 13 resultados")
            informe.append(
                {
                    "etapa": etapa,
                    "casos": len(filas),
                    "funcion_instalada_correctos": actuales,
                    "expresion_propuesta_correctos": propuestos,
                }
            )
    return informe


def probar_backend() -> int:
    import pytest
    from sqlalchemy import create_engine

    from app.core.config.settings import get_settings
    from app.core.database import db

    engine = create_engine("mssql+pyodbc://", creator=conectar)

    def motor_local(database):
        if database != "cooperativa":
            raise RuntimeError("Solo se permite el laboratorio CooperativaDB_AC02_Lab")
        return engine

    try:
        with pytest.MonkeyPatch.context() as patch:
            patch.setenv("COOPERATIVA_DB_SERVER", SERVER)
            patch.setenv("COOPERATIVA_DB_NAME", DATABASE)
            patch.delenv("AC02_ID_TRANSACCION_PRUEBA", raising=False)
            patch.setattr(db, "get_engine", motor_local)
            get_settings.cache_clear()
            return pytest.main(
                [
                    "tests/integration/test_ac02_corte_sql.py",
                    "tests/integration/test_contabilidad_db.py",
                    "-q",
                    "--tb=short",
                ]
            )
    finally:
        engine.dispose()
        get_settings.cache_clear()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--create", action="store_true")
    parser.add_argument("--backend-tests", action="store_true")
    args = parser.parse_args()
    if args.create:
        crear()
    print(json.dumps(ciclo(), indent=2))
    if args.backend_tests:
        raise SystemExit(probar_backend())


if __name__ == "__main__":
    main()
