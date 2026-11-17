"""Ejercicio SQL local tras el corte E2-01. Recibe una base de ensayo ya creada."""

import importlib.util
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
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
                INSERT Contabilidad.ConceptoContable (IdConceptoContable) VALUES (1);
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
            IF COL_LENGTH('Contabilidad.ConceptoContable','CodigoConcepto') IS NULL
                ALTER TABLE Contabilidad.ConceptoContable ADD CodigoConcepto varchar(30),
                    ConceptoDetalle varchar(100), Estado varchar(10);
        """)
        db.execute("""
            INSERT Contabilidad.TiposAsiento (IdTipoAsiento,Codigo,Nombre,Descripcion,EsManual,Estado)
            SELECT s.Id,s.Codigo,s.Codigo,s.Codigo,0,'A'
            FROM (VALUES (1001,'CAJA_DOTACION'),(1002,'CAJA_DEVOLUCION'),
                         (1003,'ATM_DOTACION'),(1004,'CAJA_DEPOSITO')) s(Id,Codigo)
            WHERE NOT EXISTS (SELECT 1 FROM Contabilidad.TiposAsiento t WHERE t.Codigo=s.Codigo);
            INSERT Contabilidad.ConceptoContable (IdConceptoContable,CodigoConcepto,ConceptoDetalle,Estado)
            SELECT s.Id,s.Codigo,s.Codigo,'Activo'
            FROM (VALUES (2,'DOT_CAJA'),(3,'DEV_CAJA'),(4,'DOT_ATM'),(5,'DEP_EFECTIVO')) s(Id,Codigo)
            WHERE NOT EXISTS (SELECT 1 FROM Contabilidad.ConceptoContable c WHERE c.CodigoConcepto=s.Codigo);
        """)
        for _ in range(2):
            lab.batches(db, migraciones / "20261117_e401_versiones_semilla.sql")

    def conectar():
        conn = lab.connect(database)
        conn.autocommit = False
        return conn

    engine = create_engine("mssql+pyodbc://", creator=conectar)
    operacion = OperacionContable(
        "DOT_CAJA",
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
        ahorro = conn.execute(
            text("""
            SELECT IdCuentaContable FROM Contabilidad.CuentasContables WHERE CodigoCuenta='21013505'
        """)
        ).scalar_one()
        casos = (
            ("DEV_CAJA", ("11010505", "11010510"), {}),
            ("DOT_ATM", ("11010515", "11010505"), {}),
            (
                "CAJA_DEPOSITO",
                ("11010510", "21013505"),
                {("PRODUCTO", "CAPITAL"): ahorro},
            ),
        )
        for codigo, cuentas, roles in casos:
            escenario = replace(
                operacion,
                codigo_plantilla=codigo,
                clave_evento=f"E401_SQL_{codigo}",
                importes={"PRINCIPAL": Decimal(100), "COMISION": Decimal(0)},
                cuentas_por_rol=roles,
            )
            id_escenario = generar_asiento(conn, escenario)
            assert [
                (m["codigo_cuenta"], m["tipo_movimiento"], m["monto"])
                for m in repository.movimientos_asiento(conn, id_escenario)
            ] == [
                (cuentas[0], "DEBITO", Decimal(100)),
                (cuentas[1], "CREDITO", Decimal(100)),
            ]
        tx.rollback()
    with engine.connect() as conn:
        assert repository.obtener_asiento(conn, id_asiento) is None

    with engine.connect() as conn:
        conn.execute(text("CREATE TABLE #E401_Negocio (Id int PRIMARY KEY)"))
        conn.commit()
        try:
            with conn.begin():
                conn.execute(text("INSERT #E401_Negocio VALUES (1)"))
                generar_asiento(
                    conn,
                    replace(
                        operacion,
                        codigo_plantilla="E401_INEXISTENTE",
                        clave_evento="E401_SQL_SIN_PLANTILLA",
                    ),
                )
        except HTTPException as error:
            assert error.detail["code"] == "PLANTILLA_NO_DEFINIDA"
        else:
            raise AssertionError("Se permitió un movimiento sin plantilla.")
        assert (
            conn.execute(text("SELECT COUNT(*) FROM #E401_Negocio")).scalar_one() == 0
        )

    def registrar(_):
        with engine.begin() as conn:
            return generar_asiento(
                conn, replace(operacion, clave_evento="E401_SQL_CONCURRENTE")
            )

    with ThreadPoolExecutor(max_workers=2) as ejecutores:
        ids = list(ejecutores.map(registrar, range(2)))
    assert ids[0] == ids[1]
    with engine.connect() as conn:
        assert len(repository.movimientos_asiento(conn, ids[0])) == 2
    print(
        "Migraciones repetibles, cuatro plantillas, comisión cero, reverso, idempotencia concurrente y rollback: OK"
    )


if __name__ == "__main__":
    probar(sys.argv[1], Path(sys.argv[2]))
