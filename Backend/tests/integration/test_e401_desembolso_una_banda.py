"""Valida y simula el manifiesto del desembolso en una copia SQL local."""

import os
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection

from app.modules.contabilidad import plantillas
from scripts.registrar_plantillas_e403 import cargar_manifiesto
from tests.integration.e201_sql_lab import connect

MANIFIESTOS = Path(__file__).resolve().parents[2] / "scripts/sql/manifiestos_e403"
NOMBRE = "credito_desembolso_cuenta_dev.json"


@pytest.fixture
def version() -> plantillas.Version:
    (fila,) = cargar_manifiesto(NOMBRE, MANIFIESTOS)
    assert fila["idTipoAsiento"] == 14
    borrador = plantillas.Version.model_validate(fila["borrador"])
    assert borrador.codigoPlantilla == "CREDITO_DESEMBOLSO_CUENTA"
    assert borrador.idConceptoContable == 7
    return borrador


def test_registrador_y_editor_aceptan_el_manifiesto(
    version: plantillas.Version,
) -> None:
    assert [
        (linea.lado, linea.base, linea.origen, linea.rol, linea.cuenta)
        for linea in version.lineas
    ] == [
        ("DEBITO", "PRINCIPAL", "PRODUCTO", "CARTERA", None),
        ("CREDITO", "PRINCIPAL", "CONTRAPRODUCTO", "CAPITAL", None),
        ("DEBITO", "IMPUESTO", "PRODUCTO", "CARTERA", None),
        ("CREDITO", "IMPUESTO", "FIJA", None, 1217),
    ]


@pytest.fixture
def sql_local():
    database = os.environ.get("E401_DESEMBOLSO_SQL_LAB", "")
    if not database:
        pytest.skip("Configure una copia SQL local E2-01 descartable.")
    if not database.startswith("CooperativaDB_E201_Lab_"):
        pytest.fail("Se requiere una copia SQL local E2-01 descartable.")

    def conectar():
        db = connect(database)
        db.autocommit = False
        return db

    engine = create_engine("mssql+pyodbc://", creator=conectar)
    try:
        with engine.connect() as conn, conn.begin() as tx:
            conn.execute(
                text("""
                IF OBJECT_ID('Contabilidad.RolCuentaProducto','U') IS NULL
                    CREATE TABLE Contabilidad.RolCuentaProducto (CodigoRol varchar(30) PRIMARY KEY);

                INSERT Contabilidad.RolCuentaProducto (CodigoRol)
                SELECT r.Codigo FROM (VALUES ('CARTERA'),('CAPITAL')) r(Codigo)
                WHERE NOT EXISTS (SELECT 1 FROM Contabilidad.RolCuentaProducto x
                                  WHERE x.CodigoRol=r.Codigo);

                IF NOT EXISTS (SELECT 1 FROM Contabilidad.CuentasContables WHERE CodigoCuenta='25059005')
                BEGIN
                    UPDATE Contabilidad.CuentasContables SET EsImputable=0
                    WHERE CodigoCuenta='250590' AND Saldo=0 AND EsImputable=1;

                    INSERT Contabilidad.CuentasContables
                        (CodigoCuenta,NombreCuenta,Naturaleza,IdCuentaSuperior,Estado,
                         EsImputable,EsCuentaValuacion,SoloAutomatica,EsCatalogoRegulador)
                    SELECT '25059005','SOLCA',Naturaleza,IdCuentaContable,1,1,0,0,0
                    FROM Contabilidad.CuentasContables WHERE CodigoCuenta='250590';
                END
                """)
            )
            yield conn
            tx.rollback()
    finally:
        engine.dispose()


def _cuenta(conn: Connection, codigo: str) -> int:
    return conn.execute(
        text("""
            SELECT IdCuentaContable FROM Contabilidad.CuentasContables
            WHERE CodigoCuenta=:codigo AND Estado=1 AND EsImputable=1
        """),
        {"codigo": codigo},
    ).scalar_one()


@pytest.mark.parametrize(
    "cartera", ["140205", "140405"], ids=["consumo", "microcredito"]
)
def test_simulacion_e403_desembolso(
    sql_local: Connection, version: plantillas.Version, cartera: str
) -> None:
    id_cartera = _cuenta(sql_local, cartera)
    id_capital = _cuenta(sql_local, "21013505")
    id_solca = _cuenta(sql_local, "25059005")
    # El manifiesto lleva el ID de Azure Dev. La simulación usa el ID de la copia.
    lineas = [
        linea.model_copy(update={"cuenta": id_solca})
        if linea.origen == "FIJA"
        else linea
        for linea in version.lineas
    ]
    resultado = plantillas.simular(
        sql_local,
        plantillas.Simulacion(
            lineas=lineas,
            montos={"PRINCIPAL": Decimal("2487.50"), "IMPUESTO": Decimal("12.50")},
            producto={"CARTERA": id_cartera},
            contraproducto={"CAPITAL": id_capital},
        ),
    )
    assert resultado["lineas"] == [
        {"cuenta": id_cartera, "lado": "DEBITO", "monto": Decimal("2487.50")},
        {"cuenta": id_capital, "lado": "CREDITO", "monto": Decimal("2487.50")},
        {"cuenta": id_cartera, "lado": "DEBITO", "monto": Decimal("12.50")},
        {"cuenta": id_solca, "lado": "CREDITO", "monto": Decimal("12.50")},
    ]
    debe_cartera = sum(
        l["monto"]
        for l in resultado["lineas"]
        if l["lado"] == "DEBITO" and l["cuenta"] == id_cartera
    )
    haber = sum(l["monto"] for l in resultado["lineas"] if l["lado"] == "CREDITO")
    assert debe_cartera == haber == resultado["total"] == Decimal("2500.00")
