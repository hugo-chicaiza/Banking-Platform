"""Valida preparación, manifiestos, editor y líneas E4-01 contra SQL Server local."""

import argparse
import json
import os
from contextlib import closing
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pyodbc
from fastapi import HTTPException
from sqlalchemy import create_engine, text

from app.modules.contabilidad import plantillas, repository
from scripts.registrar_plantillas_e403 import _MANIFIESTO

ESQUEMA = """
CREATE SCHEMA Contabilidad;
GO
CREATE SCHEMA Organizacion;
GO
CREATE TABLE Organizacion.Agencia (IdAgencia char(3) PRIMARY KEY, Estado char(1));
INSERT Organizacion.Agencia VALUES ('001','A'),('002','A');
CREATE TABLE Contabilidad.TiposAsiento (
    IdTipoAsiento int IDENTITY(1000,1) PRIMARY KEY, Codigo varchar(30) UNIQUE NOT NULL,
    Nombre varchar(100), Descripcion varchar(100), EsManual bit, Estado char(1)
);
CREATE TABLE Contabilidad.ConceptoContable (
    IdConceptoContable int IDENTITY(1000,1) PRIMARY KEY, CodigoConcepto varchar(30) UNIQUE,
    ConceptoDetalle varchar(100), Estado varchar(10)
);
CREATE TABLE Contabilidad.CuentasContables (
    IdCuentaContable int IDENTITY(1000,1) PRIMARY KEY, CodigoCuenta varchar(30) UNIQUE,
    NombreCuenta varchar(100), IdCuentaSuperior int NULL, Estado bit NOT NULL DEFAULT 1,
    EsImputable bit NOT NULL DEFAULT 1
);
CREATE TABLE Contabilidad.RolCuentaProducto (
    CodigoRol varchar(30) PRIMARY KEY, Estado char(1) NOT NULL DEFAULT 'A'
);
CREATE TABLE Contabilidad.PlantillaAsiento (
    IdPlantillaAsiento int IDENTITY(1000,1) PRIMARY KEY, CodigoPlantilla varchar(50),
    Version int, Origen varchar(30), IdTipoAsiento int REFERENCES Contabilidad.TiposAsiento,
    IdConceptoContable int REFERENCES Contabilidad.ConceptoContable, Nombre varchar(100),
    VigenciaDesde date, VigenciaHasta date NULL, Estado bit, CreadoPor int,
    AprobadoPor int NULL, FechaAprobacion datetime2 NULL, UNIQUE(CodigoPlantilla,Version)
);
CREATE TABLE Contabilidad.PlantillaAsientoDetalle (
    IdPlantillaAsiento int REFERENCES Contabilidad.PlantillaAsiento, Orden int,
    IdCuentaContable int NULL REFERENCES Contabilidad.CuentasContables,
    TipoMovimiento varchar(7), ComponenteImporte varchar(15), OrigenCuenta varchar(15),
    CodigoRol varchar(30), PRIMARY KEY(IdPlantillaAsiento,Orden)
);
INSERT Contabilidad.TiposAsiento (Codigo,Nombre,EsManual,Estado) SELECT x,x,0,'A'
FROM (VALUES ('CAJA_RETIRO'),('ATM_RETIRO'),('CAJA_FALTANTE'),('CAJA_SOBRANTE'),('BOVEDA_FALTANTE'),
             ('CUENTAS_TRANSFERENCIA'),('CUENTAS_COMISION'),('CREDITO_PAGO')) f(x);
INSERT Contabilidad.ConceptoContable (CodigoConcepto,ConceptoDetalle,Estado) SELECT x,x,'Activo'
FROM (VALUES ('RET_EFECTIVO'),('AJUSTE_FALTANTE'),('AJUSTE_SOBRANTE'),('PAGO_CREDITO')) f(x);
INSERT Contabilidad.CuentasContables (CodigoCuenta) VALUES
 ('11010510'),('11010515'),('11010505'),('19902505'),('299005'),('25909005'),
 ('4290'),('25909010'),('16909005'),('5290'),('21013505'),('21011005'),('3103'),
 ('410115'),('250105'),('140210'),('160310'),('510410'),('549005'),
 ('450420'),('450421'),('25059015'),('740405'),('7304');
INSERT Contabilidad.RolCuentaProducto (CodigoRol) VALUES
 ('CAPITAL'),('INTERES_GASTO'),('INTERES_POR_PAGAR'),('CARTERA'),
 ('INTERES_POR_COBRAR'),('INTERES_GANADO'),('DEPOSITO_NO_CUBIERTO'),('CONTRA_DEPOSITO_NO_CUBIERTO');
"""
CONTEOS = {"BASE": 4, "ACTUAL": 9, "AMPLIACION": 7, "ARQUEO": 4, "PRIMA": 1}


def ejecutar_paquete(
    db, sql: str, vigencia: date, crear: bool = False, paquete: str | None = None
):
    fecha = vigencia.isoformat()
    db.execute("EXEC sys.sp_set_session_context N'paquete_contable_vigencia', ?", fecha)
    db.execute(
        "EXEC sys.sp_set_session_context N'paquete_contable_catalogo', ?", int(crear)
    )
    base = db.execute("SELECT DB_NAME()").fetchval()
    db.execute("EXEC sys.sp_set_session_context N'paquete_contable_base', ?", base)
    db.execute(
        "EXEC sys.sp_set_session_context N'paquete_contable_paquete', ?", paquete
    )
    cursor = db.execute(sql)
    estados = {r.Familia: r.Estado for r in cursor.fetchall()}
    assert cursor.nextset()
    manifiestos = {
        r.Paquete: json.loads(r.ManifiestoJSON) if r.ManifiestoJSON else None
        for r in cursor.fetchall()
    }
    return estados, manifiestos


def verificar_editor(engine, manifiestos, vigencia: date) -> None:
    with engine.connect() as conn, conn.begin():
        cuentas = dict(
            conn.execute(
                text("""
            SELECT CodigoCuenta,IdCuentaContable FROM Contabilidad.CuentasContables
        """)
            ).all()
        )

    roles = {
        "CAPITAL": cuentas["21013505"],
        "CARTERA": cuentas["140210"],
        "INTERES_GASTO": cuentas["410115"],
        "INTERES_POR_PAGAR": cuentas["250105"],
        "INTERES_POR_COBRAR": cuentas["160310"],
        "INTERES_GANADO": cuentas["510410"],
        "DEPOSITO_NO_CUBIERTO": cuentas["740405"],
        "CONTRA_DEPOSITO_NO_CUBIERTO": cuentas["7304"],
    }
    fecha_aprobacion = vigencia - timedelta(days=1)
    for paquete, filas in manifiestos.items():
        assert len(filas) == CONTEOS[paquete]
        _MANIFIESTO.validate_python(filas)
        for fila in filas:
            tipo, borrador = fila["idTipoAsiento"], fila["borrador"]
            datos = plantillas.Version(**borrador, soloPrimeraVersion=True)
            codigo = datos.codigoPlantilla
            assert codigo is not None
            producto = dict(roles)
            if codigo.startswith("APORTE_"):
                producto["CAPITAL"] = cuentas["3103"]
            with engine.connect() as conn:
                with conn.begin():
                    solicitud = plantillas.Simulacion(
                        lineas=datos.lineas,
                        producto=producto,
                        contraproducto={"CAPITAL": cuentas["21011005"]},
                        comision=cuentas["549005"],
                        montos={linea.base: Decimal("12.50") for linea in datos.lineas},
                    )
                    simulacion = plantillas.simular(conn, solicitud)
                    assert simulacion["total"] == Decimal("12.50") * (
                        len(datos.lineas) // 2
                    )
                    if len(solicitud.montos) == 2:
                        for base in solicitud.montos:
                            parcial = solicitud.model_copy(
                                update={
                                    "montos": {**solicitud.montos, base: Decimal(0)},
                                }
                            )
                            assert plantillas.simular(conn, parcial)[
                                "total"
                            ] == Decimal("12.50")
                id_plantilla = plantillas.crear(conn, tipo, datos, 101)[
                    "idPlantillaAsiento"
                ]
                try:
                    with conn.begin():
                        plantillas.confirmar_aprobacion(
                            conn, id_plantilla, 101, fecha_aprobacion
                        )
                except HTTPException as error:
                    detalle: object = error.detail
                    assert isinstance(detalle, dict)
                    assert detalle.get("code") == "AUTOAPROBACION_PROHIBIDA"
                else:
                    raise AssertionError("El editor permitió autoaprobación.")
                with conn.begin():
                    plantillas.confirmar_aprobacion(
                        conn, id_plantilla, 102, fecha_aprobacion
                    )
                    assert (
                        repository.obtener_plantilla(conn, codigo, fecha_aprobacion)
                        is None
                    )
                    elegida = repository.obtener_plantilla(conn, codigo, vigencia)
                    assert elegida is not None
                    assert elegida["IdPlantillaAsiento"] == id_plantilla


def probar(salida: Path, vigencia: date) -> None:
    pyodbc.pooling = False
    sql_path = (
        Path(__file__).resolve().parents[2]
        / "scripts/sql/preparar_paquete_contable.sql"
    )
    sql = sql_path.read_text(encoding="utf-8")
    nombre = f"CooperativaDB_PaqueteContable_Lab_{uuid4().hex[:10]}"
    cadena = (
        "DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost;"
        "Trusted_Connection=yes;Encrypt=yes;TrustServerCertificate=yes;"
    )
    with closing(
        pyodbc.connect(cadena + "DATABASE=master;", autocommit=True)
    ) as master:
        equipo = master.execute("SELECT SERVERPROPERTY('MachineName')").fetchval()
        if str(equipo).casefold() != os.environ["COMPUTERNAME"].casefold():
            raise RuntimeError("El laboratorio exige SQL Server en el equipo local.")
        master.execute(f"CREATE DATABASE [{nombre}]")
        engine = create_engine(
            "mssql+pyodbc://",
            creator=lambda: pyodbc.connect(cadena + f"DATABASE={nombre};"),
        )
        try:
            with closing(
                pyodbc.connect(cadena + f"DATABASE={nombre};", autocommit=True)
            ) as db:
                for lote in ESQUEMA.strip().split("\nGO\n"):
                    db.execute(lote)
                estados, vista = ejecutar_paquete(db, sql, vigencia)
                base = vista["BASE"]
                assert base is not None and len(base) == 4
                assert len(estados) == sum(CONTEOS.values())
                assert all(
                    vista[p] is None
                    for p in ("ACTUAL", "AMPLIACION", "ARQUEO", "PRIMA")
                )
                _, solo_base = ejecutar_paquete(db, sql, vigencia, paquete="BASE")
                assert solo_base == {"BASE": vista["BASE"]}
                _, manifiestos = ejecutar_paquete(db, sql, vigencia, crear=True)
                assert ejecutar_paquete(db, sql, vigencia, crear=True)[1] == manifiestos
                verificar_editor(engine, manifiestos, vigencia)
                verificador = sql_path.with_name(
                    "verificar_manifiesto_contable.sql"
                ).read_text(encoding="utf-8")
                for filas in manifiestos.values():
                    assert filas is not None
                    verificacion = verificador.replace(
                        "N'[]'", "CONVERT(nvarchar(max), ?)", 1
                    )
                    resultados = db.execute(verificacion, json.dumps(filas)).fetchall()
                    assert len(resultados) == len(filas)
                    assert {r.Resultado for r in resultados} == {
                        "APROBADA_Y_SELECCIONADA"
                    }
                estados, vista = ejecutar_paquete(db, sql, vigencia)
                assert set(estados.values()) == {"FAMILIA_EXISTENTE_REVISAR"}
                assert set(vista.values()) == {None}
            salida.mkdir(parents=True, exist_ok=True)
            for paquete, filas in manifiestos.items():
                (salida / f"e403-{paquete.lower()}-laboratorio.json").write_text(
                    json.dumps(filas, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
        finally:
            engine.dispose()
            master.execute(f"DROP DATABASE [{nombre}]")
    print(
        f"{sum(CONTEOS.values())} familias y {len(CONTEOS)} manifiestos: simulación, aprobación y vigencia OK"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("salida", type=Path)
    parser.add_argument(
        "--vigencia", type=date.fromisoformat, default=date.today() + timedelta(days=14)
    )
    argumentos = parser.parse_args()
    probar(argumentos.salida, argumentos.vigencia)
