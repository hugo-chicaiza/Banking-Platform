"""Verifica la importación en una copia local posterior al corte E2-01."""

import os
import sys
from pathlib import Path

import pyodbc
from fastapi import HTTPException
from sqlalchemy import create_engine, text

from app.modules.contabilidad.importaciones import aplicar, guardar_revision, leer_csv

CABECERA = b"CodigoCuenta,NombreCuenta,CodigoCuentaSuperior,Naturaleza\n"


def probar(database: str) -> None:
    if not database.startswith("CooperativaDB_E201_Lab_"):
        raise ValueError("Se requiere una base local E2-01 de ensayo.")
    servidor = os.environ["COMPUTERNAME"]
    cadena = (
        f"DRIVER={{ODBC Driver 18 for SQL Server}};SERVER={servidor};DATABASE={database};"
        "Trusted_Connection=yes;Encrypt=yes;TrustServerCertificate=yes;"
    )

    def conectar():
        db = pyodbc.connect(cadena)
        base, instancia = db.execute("SELECT DB_NAME(), @@SERVERNAME").fetchone()
        assert base.casefold() == database.casefold()
        assert instancia.casefold() == servidor.casefold()
        db.rollback()
        return db

    migracion = (
        Path(__file__).resolve().parents[2]
        / "migrations"
        / "20261117_e203_importacion.sql"
    )
    with conectar() as db:
        sql = migracion.read_text(encoding="utf-8-sig")
        db.execute(sql)
        db.execute(sql)
    engine = create_engine("mssql+pyodbc://", creator=conectar)
    with engine.connect() as conn:
        anterior = conn.execute(
            text("""
            SELECT NombreCuenta FROM Contabilidad.CuentasContables WHERE CodigoCuenta='110197'
        """)
        ).scalar_one_or_none()
        conn.rollback()
        nombre = (
            "Importacion E203 B"
            if anterior == "Importacion E203 A"
            else "Importacion E203 A"
        )
        filas = leer_csv(
            "cuc.csv", CABECERA + f"110197,{nombre},1101,DEUDORA\n".encode()
        )
        revision = guardar_revision(conn, 101, "cuc.csv", filas)
        assert revision["revision"][0]["resultado"] == (
            "Nueva" if anterior is None else "Cambiada"
        )
        aplicado = aplicar(conn, revision["IdImportacion"], 101)
        assert aplicado["AplicadoPor"] == 101 and aplicado["FechaAplicada"]
        assert aplicar(conn, revision["IdImportacion"], 101) == aplicado
        filas = leer_csv(
            "cuc.csv", CABECERA + b"110197,Revision anterior,1101,DEUDORA\n"
        )
        revision = guardar_revision(conn, 101, "cuc.csv", filas)
        with conn.begin():
            conn.execute(
                text("""
                UPDATE Contabilidad.CuentasContables SET NombreCuenta='Cambio concurrente'
                WHERE CodigoCuenta='110197'
            """)
            )
        try:
            aplicar(conn, revision["IdImportacion"], 101)
        except HTTPException as error:
            assert (
                error.status_code == 409 and error.detail["code"] == "CATALOGO_CAMBIO"
            )
        else:
            raise AssertionError("La importación sobrescribió el cambio concurrente.")
    print("Migración repetida, aplicación, reintento y revisión obsoleta: OK")


if __name__ == "__main__":
    probar(sys.argv[1])
