"""Extracción SELECT de metadatos; instalación únicamente en bases locales marcadas."""

import json
import os
from contextlib import closing
from pathlib import Path
from typing import Literal, cast

import pyodbc

from tests.integration.atm_saldo_sql_lab import COOP, SEG, ConexionLocal, conectar

SNAPSHOT = (
    Path(__file__).resolve().parents[3] / ".local-labs" / "atm02-sql" / "schema.json"
)
ROOTS = {
    "cooperativa": {
        "Transacciones.Transaccion",
        "Transacciones.TransaccionComision",
        "Cuentas.Cuenta",
        "Cuentas.MovimientoTransaccion",
        "Tarjeta.Tarjeta",
        "Tarjeta.TarjetaHis",
        "ATM.ATM",
        "Contabilidad.FechaContable",
    },
    "seguridad": {
        "Tarjetas.TarjetaPIN",
        "Pruebas.PanFicticio",
        "Seguridad.SesionesATMRevocadas",
    },
}


def extraer() -> None:
    from app.core.config.settings import get_settings

    if os.environ.get("ATM02_SCHEMA_READ_ENABLED") != "1":
        raise RuntimeError("Lectura de metadatos de origen no autorizada")
    cfg = get_settings()
    snapshot = {}
    for db, expected in (
        ("cooperativa", "CooperativaDB"),
        ("seguridad", "SeguridadDB"),
    ):
        if getattr(cfg, db + "_db_name") != expected:
            raise RuntimeError("Origen de metadatos inesperado")
        with closing(
            pyodbc.connect(
                cfg.odbc_connection_string(
                    cast(Literal["cooperativa", "seguridad"], db)
                ),
                autocommit=True,
                readonly=True,
                timeout=10,
            )
        ) as raw:
            raw.timeout = 15

            def select(sql, params=()):
                if not sql.lstrip().upper().startswith("SELECT"):
                    raise RuntimeError("Solo metadatos SELECT en origen")
                with closing(raw.cursor()) as c:
                    c.execute(sql, params)
                    cols = [x[0] for x in c.description]
                    return [dict(zip(cols, r, strict=True)) for r in c.fetchall()]

            if select("SELECT DB_NAME() AS db")[0]["db"] != expected:
                raise RuntimeError("Base de origen inesperada")
            tables = select(
                "SELECT t.object_id AS id,s.name AS esquema,t.name FROM sys.tables t JOIN sys.schemas s ON s.schema_id=t.schema_id WHERE t.is_ms_shipped=0"
            )
            fks = select(
                "SELECT fk.object_id AS id,fk.name,fk.parent_object_id AS padre,fk.referenced_object_id AS destino,c.name AS columna,rc.name AS referencia,fkc.constraint_column_id AS posicion,fk.delete_referential_action_desc AS al_borrar,fk.update_referential_action_desc AS al_actualizar FROM sys.foreign_keys fk JOIN sys.foreign_key_columns fkc ON fkc.constraint_object_id=fk.object_id JOIN sys.columns c ON c.object_id=fkc.parent_object_id AND c.column_id=fkc.parent_column_id JOIN sys.columns rc ON rc.object_id=fkc.referenced_object_id AND rc.column_id=fkc.referenced_column_id"
            )
            modules = select(
                "SELECT o.object_id AS id,s.name AS esquema,o.name,o.type AS tipo FROM sys.sql_modules m JOIN sys.objects o ON o.object_id=m.object_id JOIN sys.schemas s ON s.schema_id=o.schema_id WHERE o.is_ms_shipped=0"
            )
            deps = select(
                "SELECT referencing_id AS padre,referenced_id AS destino,referenced_database_name AS otra_base FROM sys.sql_expression_dependencies"
            )
            triggers = select(
                "SELECT object_id AS id,parent_id AS padre,is_disabled FROM sys.triggers WHERE parent_class=1"
            )
            chosen = {
                t["id"] for t in tables if t["esquema"] + "." + t["name"] in ROOTS[db]
            }
            if len(chosen) != len(ROOTS[db]):
                raise RuntimeError("Faltan tablas raíz requeridas")
            chosen_modules = {
                m["id"]
                for m in modules
                if m["esquema"] + "." + m["name"]
                in {
                    "Transacciones.usp_AutorizarOperacion",
                    "Contabilidad.fn_IdFechaContable",
                }
            }
            stable = False
            while not stable:
                before = (chosen.copy(), chosen_modules.copy())
                chosen |= {fk["destino"] for fk in fks if fk["padre"] in chosen}
                chosen_modules |= {
                    t["id"]
                    for t in triggers
                    if t["padre"] in chosen and not t["is_disabled"]
                }
                for d in deps:
                    if d["padre"] in chosen_modules:
                        if d["otra_base"] is not None:
                            raise RuntimeError(
                                "Dependencia entre bases: requiere revisión"
                            )
                        if any(t["id"] == d["destino"] for t in tables):
                            chosen.add(d["destino"])
                        if any(m["id"] == d["destino"] for m in modules):
                            chosen_modules.add(d["destino"])
                stable = before == (chosen, chosen_modules)
            ids = ",".join(str(int(i)) for i in chosen)
            if chosen_modules:
                ids_modulos = ",".join(str(int(i)) for i in chosen_modules)
                definiciones = {
                    m["id"]: m["definition"]
                    for m in select(
                        "SELECT object_id AS id,definition FROM sys.sql_modules WHERE object_id IN (SELECT CONVERT(int,value) FROM STRING_SPLIT(?,','))",
                        (ids_modulos,),
                    )
                }
                for m in modules:
                    if m["id"] in chosen_modules:
                        m["definition"] = definiciones[m["id"]]
            columns = select(
                "SELECT c.object_id AS tabla,c.column_id AS posicion,c.name,t.name AS tipo,c.max_length,c.precision,c.scale,c.is_nullable,c.is_identity,c.collation_name,CONVERT(varchar(40),ic.seed_value) AS semilla,CONVERT(varchar(40),ic.increment_value) AS incremento,cc.definition AS calculada,dc.name AS default_nombre,dc.definition AS valor_default FROM sys.columns c JOIN sys.types t ON t.user_type_id=c.user_type_id LEFT JOIN sys.identity_columns ic ON ic.object_id=c.object_id AND ic.column_id=c.column_id LEFT JOIN sys.computed_columns cc ON cc.object_id=c.object_id AND cc.column_id=c.column_id LEFT JOIN sys.default_constraints dc ON dc.object_id=c.default_object_id WHERE c.object_id IN (SELECT CONVERT(int,value) FROM STRING_SPLIT(?,',')) ORDER BY c.object_id,c.column_id",
                (ids,),
            )
            indices = select(
                "SELECT i.object_id AS tabla,i.index_id AS id,i.name,i.type_desc,i.is_unique,i.is_primary_key,i.is_unique_constraint,i.filter_definition,ic.key_ordinal,ic.is_descending_key,ic.is_included_column,c.name AS columna FROM sys.indexes i JOIN sys.index_columns ic ON ic.object_id=i.object_id AND ic.index_id=i.index_id JOIN sys.columns c ON c.object_id=ic.object_id AND c.column_id=ic.column_id WHERE i.object_id IN (SELECT CONVERT(int,value) FROM STRING_SPLIT(?,',')) AND i.is_disabled=0 AND i.is_hypothetical=0 ORDER BY i.object_id,i.index_id,ic.index_column_id",
                (ids,),
            )
            checks = select(
                "SELECT parent_object_id AS tabla,name,definition,is_not_trusted FROM sys.check_constraints WHERE parent_object_id IN (SELECT CONVERT(int,value) FROM STRING_SPLIT(?,',')) AND is_disabled=0",
                (ids,),
            )
            snapshot[db] = {
                "tables": [t for t in tables if t["id"] in chosen],
                "columns": columns,
                "indices": indices,
                "checks": checks,
                "fks": [f for f in fks if f["padre"] in chosen],
                "modules": [m for m in modules if m["id"] in chosen_modules],
                "deps": deps,
                "compatibility": select(
                    "SELECT compatibility_level FROM sys.databases WHERE database_id=DB_ID()"
                )[0]["compatibility_level"],
            }
    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT.write_text(
        json.dumps(snapshot, ensure_ascii=True, default=str), encoding="utf-8"
    )
    print(
        {
            db: {"tablas": len(s["tables"]), "modulos": len(s["modules"])}
            for db, s in snapshot.items()
        }
    )


def q(name):
    return "[" + name.replace("]", "]]") + "]"


def tipo(c):
    value = q(c["tipo"])
    if c["tipo"] in ("varchar", "char", "varbinary", "binary", "nvarchar", "nchar"):
        size = c["max_length"]
        value += (
            "("
            + (
                "max"
                if size == -1
                else str(size // 2 if c["tipo"].startswith("n") else size)
            )
            + ")"
        )
    elif c["tipo"] in ("decimal", "numeric"):
        value += f"({c['precision']},{c['scale']})"
    elif c["tipo"] in ("time", "datetime2", "datetimeoffset"):
        value += f"({c['scale']})"
    return value


def instalar() -> None:
    data = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    for key, database in (("cooperativa", COOP), ("seguridad", SEG)):
        s = data[key]
        tables = {t["id"]: q(t["esquema"]) + "." + q(t["name"]) for t in s["tables"]}
        with closing(conectar(database, autocommit=True)) as raw:
            conn = ConexionLocal(raw, database)
            with closing(conn.cursor()) as c:
                if c.execute(
                    "SELECT COUNT(*) FROM sys.tables WHERE is_ms_shipped=0"
                ).fetchval():
                    raise RuntimeError(
                        "Esquema local ya contiene tablas: no sobrescribir"
                    )
                for schema in sorted(
                    {t["esquema"] for t in s["tables"]}
                    | {m["esquema"] for m in s["modules"]}
                ):
                    if schema != "dbo":
                        c.execute("CREATE SCHEMA " + q(schema))
                for ident, table in tables.items():
                    parts = []
                    for col in (x for x in s["columns"] if x["tabla"] == ident):
                        part = q(col["name"])
                        if col["calculada"]:
                            part += " AS " + col["calculada"]
                        else:
                            part += " " + tipo(col)
                            if col["collation_name"]:
                                part += " COLLATE " + col["collation_name"]
                            if col["is_identity"]:
                                part += (
                                    f" IDENTITY({col['semilla']},{col['incremento']})"
                                )
                            part += " NULL" if col["is_nullable"] else " NOT NULL"
                            if col["valor_default"]:
                                part += (
                                    " CONSTRAINT "
                                    + q(col["default_nombre"])
                                    + " DEFAULT "
                                    + col["valor_default"]
                                )
                        parts.append(part)
                    c.execute("CREATE TABLE " + table + " (" + ", ".join(parts) + ")")
                groups = {}
                for i in s["indices"]:
                    groups.setdefault((i["tabla"], i["id"]), []).append(i)
                for (ident, _), group in groups.items():
                    i = group[0]
                    keys = ",".join(
                        q(x["columna"])
                        + (" DESC" if x["is_descending_key"] else " ASC")
                        for x in sorted(group, key=lambda x: x["key_ordinal"])
                        if x["key_ordinal"] > 0
                    )
                    included = [
                        q(x["columna"]) for x in group if x["is_included_column"]
                    ]
                    if i["is_primary_key"] or i["is_unique_constraint"]:
                        sql = (
                            "ALTER TABLE "
                            + tables[ident]
                            + " ADD CONSTRAINT "
                            + q(i["name"])
                            + (" PRIMARY KEY " if i["is_primary_key"] else " UNIQUE ")
                            + i["type_desc"]
                            + " ("
                            + keys
                            + ")"
                        )
                    else:
                        sql = (
                            "CREATE "
                            + ("UNIQUE " if i["is_unique"] else "")
                            + i["type_desc"]
                            + " INDEX "
                            + q(i["name"])
                            + " ON "
                            + tables[ident]
                            + " ("
                            + keys
                            + ")"
                        )
                        if included:
                            sql += " INCLUDE (" + ",".join(included) + ")"
                        if i["filter_definition"]:
                            sql += " WHERE " + i["filter_definition"]
                    c.execute(sql)
                for ck in s["checks"]:
                    c.execute(
                        "ALTER TABLE "
                        + tables[ck["tabla"]]
                        + (" WITH NOCHECK" if ck["is_not_trusted"] else " WITH CHECK")
                        + " ADD CONSTRAINT "
                        + q(ck["name"])
                        + " CHECK "
                        + ck["definition"]
                    )
                groups = {}
                for f in s["fks"]:
                    groups.setdefault(f["id"], []).append(f)
                for group in groups.values():
                    group.sort(key=lambda x: x["posicion"])
                    f = group[0]
                    sql = (
                        "ALTER TABLE "
                        + tables[f["padre"]]
                        + " WITH CHECK ADD CONSTRAINT "
                        + q(f["name"])
                        + " FOREIGN KEY ("
                        + ",".join(q(x["columna"]) for x in group)
                        + ") REFERENCES "
                        + tables[f["destino"]]
                        + " ("
                        + ",".join(q(x["referencia"]) for x in group)
                        + ")"
                    )
                    if f["al_borrar"] != "NO_ACTION":
                        sql += " ON DELETE " + f["al_borrar"].replace("_", " ")
                    if f["al_actualizar"] != "NO_ACTION":
                        sql += " ON UPDATE " + f["al_actualizar"].replace("_", " ")
                    c.execute(sql)
                pending = {m["id"]: m for m in s["modules"]}
                while pending:
                    ready = [
                        ident
                        for ident in pending
                        if not any(
                            d["padre"] == ident
                            and d["destino"] in pending
                            and d["destino"] != ident
                            for d in s["deps"]
                        )
                    ]
                    if not ready:
                        raise RuntimeError("Dependencia cíclica de módulos: detener")
                    for ident in ready:
                        definition = pending.pop(ident)["definition"]
                        if not definition:
                            raise RuntimeError("Definición SQL no visible")
                        c.execute(definition)
        print(
            {
                "base_local": database,
                "tablas_instaladas": len(tables),
                "modulos_instalados": len(s["modules"]),
            }
        )
