"""Ejercicio SQL local tras el corte E2-01. Recibe una base de ensayo ya creada."""

import importlib.util
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine, text

from app.modules.contabilidad import repository
from app.modules.contabilidad.asientos import (
    OperacionContable,
    generar_asiento,
    reversar,
)


def probar(database: str, laboratorio: Path) -> None:
    if not database.startswith("CooperativaDB_E201_Lab_"):
        raise ValueError("Se requiere una base E2-01 de ensayo.")
    spec = importlib.util.spec_from_file_location("e201_sql_lab", laboratorio)
    assert spec is not None and spec.loader is not None
    lab = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lab)
    with lab.connect(database) as db:
        db.execute("""
            IF COL_LENGTH('Contabilidad.FechaContable','EsFeriado') IS NULL
                ALTER TABLE Contabilidad.FechaContable ADD EsFeriado bit NOT NULL DEFAULT (0),
                    EsFinDeSemana bit NOT NULL DEFAULT (0), HoraCorte time NULL;
            IF NOT EXISTS (SELECT 1 FROM Contabilidad.FechaContable WHERE IdFechaContable=9998)
                INSERT Contabilidad.FechaContable (IdFechaContable,Fecha,EsDiaContable)
                VALUES (9998,'20261015',1);
            IF OBJECT_ID('Contabilidad.ConceptoContable','U') IS NULL
                CREATE TABLE Contabilidad.ConceptoContable(IdConceptoContable int PRIMARY KEY);
            IF NOT EXISTS (SELECT 1 FROM Contabilidad.ConceptoContable WHERE IdConceptoContable=1)
                INSERT Contabilidad.ConceptoContable VALUES (1);
            IF SCHEMA_ID('Organizacion') IS NULL EXEC('CREATE SCHEMA Organizacion');
            IF OBJECT_ID('Organizacion.Agencia','U') IS NULL
                CREATE TABLE Organizacion.Agencia(IdAgencia char(3) PRIMARY KEY);
            IF NOT EXISTS (SELECT 1 FROM Organizacion.Agencia WHERE IdAgencia='001')
                INSERT Organizacion.Agencia VALUES ('001');
        """)
        # La numeración nativa se carga desde una de las proyecciones previas.
        import json

        inspeccion = json.loads(
            (lab.FIXTURES / "e201-inspect.json").read_text(encoding="utf-8")
        )
        for proyeccion in inspeccion.values():
            coincidencia = next(
                (
                    m["definition"]
                    for m in proyeccion.get("modules", [])
                    if m["name"] == "usp_GenerarNumeroAsiento"
                ),
                None,
            )
            if coincidencia:
                db.execute(
                    coincidencia.replace(
                        "CREATE   PROCEDURE", "CREATE OR ALTER PROCEDURE", 1
                    )
                )
                break
        else:
            raise RuntimeError(
                "Falta el procedimiento de numeración en las proyecciones."
            )
        migraciones = Path(__file__).resolve().parents[2] / "migrations"
        for _ in range(2):
            for nombre in (
                "20261111_ac01_01_plantillas_asiento.sql",
                "20261111_ac01_02_periodo_asiento.sql",
                "20261117_e401_versiones.sql",
            ):
                lab.batches(db, migraciones / nombre)
        db.execute("""
            IF NOT EXISTS (SELECT 1 FROM Contabilidad.PlantillaAsiento WHERE CodigoPlantilla='E401_DOTACION')
            BEGIN
                INSERT Contabilidad.PlantillaAsiento (CodigoPlantilla,IdConceptoContable,Origen,IdTipoAsiento,Nombre,Estado)
                VALUES ('E401_DOTACION',1,'CAJA',1000,'Dotacion laboratorio',1);
                DECLARE @id int=SCOPE_IDENTITY();
                INSERT Contabilidad.PlantillaAsientoDetalle
                    (IdPlantillaAsiento,Orden,IdCuentaContable,TipoMovimiento,ComponenteImporte)
                SELECT @id,1,IdCuentaContable,'DEBITO','PRINCIPAL' FROM Contabilidad.CuentasContables WHERE CodigoCuenta='11010510'
                UNION ALL
                SELECT @id,2,IdCuentaContable,'CREDITO','PRINCIPAL' FROM Contabilidad.CuentasContables WHERE CodigoCuenta='11010505';
            END
        """)

    def conectar():
        conn = lab.connect(database)
        conn.autocommit = False
        return conn

    engine = create_engine("mssql+pyodbc://", creator=conectar)
    operacion = OperacionContable(
        "E401_DOTACION",
        "E401_SQL_DOTACION",
        "001",
        287,
        101,
        datetime(2026, 10, 14, 18),
        {"PRINCIPAL": Decimal(500)},
    )
    with engine.connect() as conn, conn.begin() as tx:
        antes = conn.execute(
            text(
                "SELECT Saldo FROM Contabilidad.CuentasContables WHERE CodigoCuenta='11010510'"
            )
        ).scalar_one()
        id_asiento = generar_asiento(conn, operacion)
        assert generar_asiento(conn, operacion) == id_asiento
        detalle = repository.movimientos_asiento(conn, id_asiento)
        assert [
            (m["codigo_cuenta"], m["tipo_movimiento"], m["monto"]) for m in detalle
        ] == [
            ("11010510", "DEBITO", Decimal(500)),
            ("11010505", "CREDITO", Decimal(500)),
        ]
        despues = conn.execute(
            text(
                "SELECT Saldo FROM Contabilidad.CuentasContables WHERE CodigoCuenta='11010510'"
            )
        ).scalar_one()
        assert despues == antes + 500
        with patch(
            "app.modules.contabilidad.service.resolver_id_fecha_contable",
            return_value=9998,
        ):
            espejo = reversar(conn, id_asiento, "Prueba local", actor=102)
        cabecera = repository.obtener_asiento(conn, espejo)
        assert cabecera["fecha_asiento"].isoformat() == "2026-10-15"
        assert cabecera["id_asiento_reversion"] == id_asiento
        assert repository.obtener_asiento(conn, id_asiento)["estado"] == "REVERSADO"
        try:
            reversar(conn, id_asiento, "Reintento", actor=102)
        except HTTPException as error:
            assert (
                error.status_code == 409
                and error.detail["code"] == "ASIENTO_YA_REVERSADO"
            )
        else:
            raise AssertionError("Se permitió un segundo reverso.")
        saldo = conn.execute(
            text(
                "SELECT Saldo FROM Contabilidad.CuentasContables WHERE CodigoCuenta='11010510'"
            )
        ).scalar_one()
        assert saldo == antes
        tx.rollback()
    with engine.connect() as conn:
        assert repository.obtener_asiento(conn, id_asiento) is None
    print(
        "Migraciones repetibles, dotación 500, idempotencia, saldos, reverso y rollback: OK"
    )


if __name__ == "__main__":
    probar(sys.argv[1], Path(sys.argv[2]))
