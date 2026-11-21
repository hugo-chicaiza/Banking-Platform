"""E2-01: local SQL Server only; never imports settings or reads .env."""

import json
import os
import re
from pathlib import Path

import pyodbc

ROOT = Path(__file__).resolve().parents[3]
SERVER = "DESKTOP-OR5GE4R"
FIXTURES = Path(os.environ.get("E201_FIXTURES", ROOT / ".local-labs"))


def connect(database):
    if database != "master" and not database.startswith("CooperativaDB_"):
        raise RuntimeError("Not a local lab database")
    conn = pyodbc.connect(
        f"DRIVER={{ODBC Driver 18 for SQL Server}};SERVER={SERVER};DATABASE={database};"
        "Trusted_Connection=yes;Encrypt=yes;TrustServerCertificate=yes;",
        autocommit=True,
        timeout=10,
    )
    assert conn.execute("SELECT @@SERVERNAME").fetchval() == SERVER
    return conn


def rows(conn, sql):
    cur = conn.execute(sql)
    return [dict(zip([c[0] for c in cur.description], r)) for r in cur.fetchall()]


def batches(conn, path):
    for batch in re.split(
        r"^\s*GO\s*$",
        path.read_text(encoding="utf-8"),
        flags=re.MULTILINE | re.IGNORECASE,
    ):
        if batch.strip():
            cur = conn.execute(batch)
            while cur.nextset():
                pass


def quote(name):
    return "[" + name.replace("]", "]]") + "]"


def fixture(conn):
    data = json.loads(
        (FIXTURES / "ac01-completar-readonly.json").read_text(encoding="utf-8")
    )
    inspected = json.loads((FIXTURES / "e201-inspect.json").read_text(encoding="utf-8"))
    data["cuentas"] = inspected["CooperativaDB_AC01_Segmento1_20261113_v2"]["accounts"]
    assert len(data["cuentas"]) == 1182
    conn.execute("CREATE SCHEMA Contabilidad")
    for table, key, data_key in [
        ("ElementoCUC", "CodigoElemento", "elementos"),
        ("CuentasContables", "IdCuentaContable", "cuentas"),
        ("AsientoContable", "IdAsientoContable", "todos_asientos"),
        ("MovimientosContables", "IdMovimientoContable", "todos_movimientos"),
    ]:
        cols = [c for c in data["columnas"] if c["tabla"] == table]
        definitions = []
        for col in cols:
            if col["calculada"]:
                definitions.append(
                    quote(col["name"])
                    + " AS "
                    + col["calculada"]
                    + (" PERSISTED" if col["is_persisted"] else "")
                )
                continue
            typ = col["tipo"]
            if typ in ("varchar", "nvarchar", "char", "nchar", "varbinary", "binary"):
                size = col["max_length"]
                typ += (
                    "("
                    + (
                        "max"
                        if size == -1
                        else str(size // 2 if typ.startswith("n") else size)
                    )
                    + ")"
                )
            elif typ in ("decimal", "numeric"):
                typ += f"({col['precision']},{col['scale']})"
            line = quote(col["name"]) + " " + typ
            if col["collation_name"]:
                line += " COLLATE " + col["collation_name"]
            if col["is_identity"]:
                line += " IDENTITY(1,1)"
            line += " NULL" if col["is_nullable"] else " NOT NULL"
            if col["defecto"]:
                line += " DEFAULT " + col["defecto"]
            definitions.append(line)
        conn.execute(
            "CREATE TABLE Contabilidad."
            + quote(table)
            + " ("
            + ",".join(definitions)
            + ",PRIMARY KEY("
            + quote(key)
            + "))"
        )
        writable = [c["name"] for c in cols if not c["calculada"]]
        identity = any(c["is_identity"] for c in cols)
        if identity:
            conn.execute("SET IDENTITY_INSERT Contabilidad." + quote(table) + " ON")
        sql = (
            "INSERT INTO Contabilidad."
            + quote(table)
            + "("
            + ",".join(map(quote, writable))
            + ") VALUES ("
            + ",".join("?" for _ in writable)
            + ")"
        )
        for row in data[data_key]:
            conn.execute(sql, [row[n] for n in writable])
        if identity:
            conn.execute("SET IDENTITY_INSERT Contabilidad." + quote(table) + " OFF")
    for check in data["checks"]:
        conn.execute(
            "ALTER TABLE Contabilidad."
            + quote(check["tabla"])
            + " WITH CHECK ADD CONSTRAINT "
            + quote(check["name"])
            + " CHECK "
            + check["definition"]
        )
    conn.execute(
        "ALTER TABLE Contabilidad.CuentasContables ADD CONSTRAINT UQ_E201_Codigo UNIQUE(CodigoCuenta)"
    )
    conn.execute(
        "ALTER TABLE Contabilidad.CuentasContables ADD FOREIGN KEY(IdCuentaSuperior) REFERENCES Contabilidad.CuentasContables(IdCuentaContable)"
    )
    conn.execute(
        "ALTER TABLE Contabilidad.CuentasContables ADD FOREIGN KEY(CodigoElemento) REFERENCES Contabilidad.ElementoCUC(CodigoElemento)"
    )
    conn.execute(
        "ALTER TABLE Contabilidad.MovimientosContables ADD FOREIGN KEY(IdAsientoContable) REFERENCES Contabilidad.AsientoContable(IdAsientoContable)"
    )
    conn.execute(
        "ALTER TABLE Contabilidad.MovimientosContables ADD FOREIGN KEY(IdCuentaContable) REFERENCES Contabilidad.CuentasContables(IdCuentaContable)"
    )
    # Business tables are minimal projections: not a full clone of Azure.
    conn.execute("CREATE SCHEMA Transacciones")
    conn.execute(
        "CREATE TABLE Transacciones.Transaccion(IdTransaccion bigint PRIMARY KEY,TipoTransaccion varchar(30),IdCuenta int)"
    )
    conn.execute(
        "CREATE TABLE Transacciones.TipoTransaccion(CodigoTipo varchar(30),AfectaSaldo bit)"
    )
    conn.execute(
        "CREATE TABLE Contabilidad.FechaContable(IdFechaContable int PRIMARY KEY,Fecha date,EsDiaContable bit)"
    )
    dates = {a["IdFechaContable"]: a["FechaAsiento"] for a in data["todos_asientos"]}
    for key, date in dates.items():
        conn.execute("INSERT Contabilidad.FechaContable VALUES(?,?,1)", key, date)
    conn.execute(
        "CREATE TABLE Contabilidad.PeriodoContable(Anio int,Mes int,Estado varchar(20))"
    )
    conn.execute("INSERT Contabilidad.PeriodoContable VALUES(2026,10,'ABIERTO')")
    conn.execute(
        "CREATE TABLE Contabilidad.TiposAsiento(IdTipoAsiento int PRIMARY KEY,Codigo varchar(30),EsManual bit,Estado char(1),Nombre varchar(80),Descripcion varchar(250))"
    )
    conn.execute(
        "INSERT Contabilidad.TiposAsiento VALUES(999,'MANUAL_RECLASIFICACION',1,'A','Reclasificacion','Prueba'),(1000,'PRUEBA_AUTOMATICA',0,'A','Automatico','Prueba')"
    )
    for trigger in data["triggers"]:
        conn.execute(trigger["definicion"])
    for module in inspected["CooperativaDB_AC01_Lab"]["modules"]:
        if module["name"] in ("trg_AsientoContable_Reglas", "usp_ContabilizarAsiento"):
            conn.execute(module["definition"])
    return data


def expect_error(conn, sql, code=None):
    try:
        conn.execute(sql)
    except pyodbc.Error as error:
        if code is not None:
            assert str(code) in str(error), str(error)
        if conn.execute("SELECT XACT_STATE()").fetchval():
            conn.execute("ROLLBACK")
        return str(error)
    raise AssertionError("Expected SQL rejection: " + sql)


def capture_savings(conn):
    cur = conn.execute(
        (
            ROOT / "Backend/scripts/sql/e201/003_captura_ahorro_solo_lectura.sql"
        ).read_text(encoding="utf-8")
    )
    sets = []
    while True:
        if cur.description:
            sets.append(
                [dict(zip([c[0] for c in cur.description], r)) for r in cur.fetchall()]
            )
        if not cur.nextset():
            return sets


def new_entry(conn, number, manual=True):
    return conn.execute(
        """SET NOCOUNT ON; INSERT Contabilidad.AsientoContable
      (NumeroAsiento,FechaAsiento,FechaSistema,IdTipoAsiento,Origen,Concepto,
       TotalDebito,TotalCredito,Estado,IdUsuarioCreacion,IdAgencia,IdFechaContable)
      VALUES(?,'20261014','20261014 18:00:00',?,'AJUSTE','E201 ensayo local',0,0,'BORRADOR',101,'001',287);
      SELECT CONVERT(int,SCOPE_IDENTITY());""",
        number,
        999 if manual else 1000,
    ).fetchval()
