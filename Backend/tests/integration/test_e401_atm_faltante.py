"""Ensayo de ATM_FALTANTE con SQL Server local y proyección E4-01 instalada."""

import json
import os
from contextlib import closing
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pyodbc
import pytest
from sqlalchemy import create_engine, text

from app.modules.contabilidad import plantillas
from app.modules.contabilidad.asientos import OperacionContable
from tests.integration.e201_sql_lab import connect
from tests.integration.e401_catalogo_lab import (
    Familia,
    Linea,
    _catalogos,
    _cuenta,
    _fecha,
    _probar_asiento,
    _version,
)

BACKEND = Path(__file__).resolve().parents[2]


def test_migracion_manifiesto_simulacion_y_asiento_atm_faltante() -> None:
    database = os.environ.get("E401_ATM_FALTANTE_SQL_LAB", "")
    if not database:
        pytest.skip("Configure una copia SQL descartable con E2-01 y E4-01.")
    assert database.startswith("CooperativaDB_E201_Lab_")
    migracion = (
        BACKEND
        / "migrations/cooperativa/202611271200_contabilidad_atm_faltantes.up.sql"
    ).read_text(encoding="utf-8")

    with closing(connect(database)) as db:
        with pytest.raises(pyodbc.Error, match="57930"):
            db.execute(migracion)
        db.execute(
            "EXEC sys.sp_set_session_context @key=N'migration_database', @value=?",
            database,
        )
        db.execute(migracion)
        original = db.execute(
            "SELECT IdCuentaContable FROM Contabilidad.CuentasContables WHERE CodigoCuenta='19902515'"
        ).fetchval()
        assert (
            db.execute(
                "SELECT Saldo FROM Contabilidad.CuentasContables WHERE IdCuentaContable=?",
                original,
            ).fetchval()
            == 0
        )
        db.execute(migracion)
        assert (
            db.execute(
                "SELECT IdCuentaContable FROM Contabilidad.CuentasContables WHERE CodigoCuenta='19902515'"
            ).fetchval()
            == original
        )
        db.execute(
            "UPDATE Contabilidad.CuentasContables SET EsImputable=0 WHERE IdCuentaContable=?",
            original,
        )
        try:
            with pytest.raises(pyodbc.Error, match="57933"):
                db.execute(migracion)
        finally:
            db.execute(
                "UPDATE Contabilidad.CuentasContables SET EsImputable=1 WHERE IdCuentaContable=?",
                original,
            )
        db.execute(
            "UPDATE Contabilidad.CuentasContables SET Saldo=1 WHERE IdCuentaContable=?",
            original,
        )
        try:
            with pytest.raises(pyodbc.Error, match="57935"):
                db.execute(migracion)
        finally:
            db.execute(
                "UPDATE Contabilidad.CuentasContables SET Saldo=0 WHERE IdCuentaContable=?",
                original,
            )

    def conectar():
        db = connect(database)
        db.autocommit = False
        return db

    engine = create_engine("mssql+pyodbc://", creator=conectar)
    try:
        fecha = date(2026, 11, 30)
        familia = Familia(
            "ATM_FALTANTE",
            "ATM_FALTANTE",
            "AJUSTE_FALTANTE",
            (
                Linea("DEBITO", "DIFERENCIA", "FIJA", None, "19902515"),
                Linea("CREDITO", "DIFERENCIA", "FIJA", None, "11010515"),
            ),
        )
        with engine.connect() as conn, conn.begin() as tx:
            dia_anterior = _fecha(conn, date(2026, 11, 27))
            dia = _fecha(conn, fecha)
            # El calendario mínimo de la proyección no contiene la función.
            # Se fija el día anterior solo durante el caso de generación.
            if (
                conn.scalar(text("SELECT OBJECT_ID('Contabilidad.fn_IdFechaContable')"))
                is None
            ):
                conn.exec_driver_sql(
                    "CREATE FUNCTION Contabilidad.fn_IdFechaContable(@instante datetime2) "
                    f"RETURNS int AS BEGIN RETURN {dia_anterior}; END"
                )
            _catalogos(conn, familia)
            conn.execute(
                text(
                    "EXEC sys.sp_set_session_context @key=N'atm_faltante_vigencia', @value='2026-11-30'"
                )
            )
            try:
                driver = conn.connection.driver_connection
                assert isinstance(driver, pyodbc.Connection)
                with closing(driver.cursor()) as cursor:
                    cursor.execute(
                        (BACKEND / "scripts/sql/preparar_atm_faltante.sql").read_text(
                            encoding="utf-8"
                        )
                    )
                    while cursor.description is None and cursor.nextset():
                        pass
                    manifiesto = cursor.fetchone()
                    assert manifiesto is not None
            finally:
                conn.execute(
                    text(
                        "EXEC sys.sp_set_session_context @key=N'atm_faltante_vigencia', @value=NULL"
                    )
                )
            (fila,) = json.loads(manifiesto.ManifiestoJSON)
            borrador = plantillas.Version.model_validate(fila["borrador"])
            registro = plantillas.Version.model_validate_json(
                manifiesto.RegistroSwaggerJSON
            )
            assert registro == borrador.model_copy(update={"soloPrimeraVersion": True})
            simulacion = plantillas.Simulacion.model_validate_json(
                manifiesto.SimulacionSwaggerJSON
            )
            assert simulacion.lineas == borrador.lineas
            assert simulacion.montos == {"DIFERENCIA": Decimal("50.00")}
            debe = _cuenta(conn, "19902515")
            haber = _cuenta(conn, "11010515")
            resultado = plantillas.simular(conn, simulacion)
            assert resultado == {
                "total": Decimal("50.00"),
                "lineas": [
                    {"cuenta": debe, "lado": "DEBITO", "monto": Decimal("50.00")},
                    {"cuenta": haber, "lado": "CREDITO", "monto": Decimal("50.00")},
                ],
            }
            tx.rollback()
        with engine.begin() as conn:
            dia = _fecha(conn, fecha)
            plantilla = _version(conn, familia, 1, fecha)
        modelo = OperacionContable(
            familia.codigo,
            "ATM_CUADRE_LOCAL",
            "001",
            dia,
            101,
            datetime(2026, 11, 30, 12),
            {"DIFERENCIA": Decimal("50.00")},
        )
        try:
            _probar_asiento(
                engine, familia, plantilla, fecha, dia, modelo, monto_inicial=50
            )
        finally:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "DELETE Contabilidad.PlantillaAsientoDetalle WHERE IdPlantillaAsiento=:id"
                    ),
                    {"id": plantilla},
                )
                conn.execute(
                    text(
                        "DELETE Contabilidad.PlantillaAsiento WHERE IdPlantillaAsiento=:id"
                    ),
                    {"id": plantilla},
                )
    finally:
        engine.dispose()
