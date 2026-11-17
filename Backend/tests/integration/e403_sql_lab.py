"""Prueba versiones sobre la semilla de dotación del ensayo SQL E4-01."""

import os
import sys
from datetime import date

import pyodbc
from fastapi import HTTPException
from sqlalchemy import create_engine, text

from app.modules.contabilidad import plantillas, repository


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

    engine = create_engine("mssql+pyodbc://", creator=conectar)
    hoy, futuro = date(2026, 10, 14), date(2026, 10, 15)
    with engine.connect() as conn:
        cuentas = {
            codigo: cuenta
            for codigo, cuenta in conn.execute(
                text("""
                SELECT CodigoCuenta,IdCuentaContable FROM Contabilidad.CuentasContables
                WHERE CodigoCuenta IN ('11010505','11010510')
            """)
            )
        }
        conn.rollback()
        datos = plantillas.Version(
            vigenciaDesde=futuro,
            nombre="Dotación de ensayo E4-03",
            lineas=[
                plantillas.Linea(
                    lado=lado, origen="FIJA", base="PRINCIPAL", cuenta=cuentas[codigo]
                )
                for lado, codigo in (("DEBITO", "11010510"), ("CREDITO", "11010505"))
            ],
        )
        nueva = plantillas.crear(conn, 1001, datos, 101)["idPlantillaAsiento"]
        try:
            with conn.begin():
                plantillas.confirmar_aprobacion(conn, nueva, 101, hoy)
        except HTTPException as error:
            assert error.detail["code"] == "AUTOAPROBACION_PROHIBIDA"
        else:
            raise AssertionError("Se permitió la autoaprobación.")
        with conn.begin() as transaccion:
            anterior = repository.obtener_plantilla(conn, "DOT_CAJA", futuro)
            assert anterior and anterior["IdPlantillaAsiento"] != nueva
            plantillas.confirmar_aprobacion(conn, nueva, 102, hoy)
            actual = repository.obtener_plantilla(conn, "DOT_CAJA", hoy)
            programada = repository.obtener_plantilla(conn, "DOT_CAJA", futuro)
            assert (
                actual
                and actual["IdPlantillaAsiento"] == anterior["IdPlantillaAsiento"]
            )
            assert programada and programada["IdPlantillaAsiento"] == nueva
            transaccion.rollback()
    print("Pendiente, rechazo a autoaprobación y selección por vigencia: OK")


if __name__ == "__main__":
    probar(sys.argv[1])
