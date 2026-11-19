"""Genera la migración cero de una base (E0-01) leyendo su catálogo. Solo lee.

    python scripts/generar_linea_base.py --base cooperativa > migrations/cooperativa/000000000000_linea_base.up.sql
    python scripts/generar_linea_base.py --base seguridad --semillas Catalogo.Paises,Catalogo.Ciudad

Usa `MIGRACIONES_ODBC_<BASE>` (login administrativo: ve todo, incluido lo que el login de
la aplicación ya no ve). Produce, en orden: esquemas, tablas (columnas, identidad,
valores por defecto, columnas calculadas, clave primaria y únicas), índices, claves
foráneas, restricciones CHECK y módulos (vistas, funciones, procedimientos,
disparadores). Con `--semillas`, agrega un MERGE por clave primaria de cada tabla de
referencia (repetible). Revise el resultado y compárelo con la base compartida antes de
confirmarlo: es la estructura de partida de una base vacía.
"""

import argparse
import sys
from datetime import date, datetime, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import URL, create_engine, text

from app.core.config.settings import get_settings

_ESQUEMAS_SISTEMA = ("dbo", "sys", "INFORMATION_SCHEMA", "guest")


def _q(nombre: str) -> str:
    return "[" + nombre.replace("]", "]]") + "]"


def _tipo(t: str, largo: int, precision: int, escala: int) -> str:
    if t in ("varchar", "char", "varbinary", "binary"):
        return f"{t}({'max' if largo == -1 else largo})"
    if t in ("nvarchar", "nchar"):
        return f"{t}({'max' if largo == -1 else largo // 2})"
    if t in ("decimal", "numeric"):
        return f"{t}({precision},{escala})"
    if t in ("datetime2", "time", "datetimeoffset"):
        return f"{t}({escala})"
    return t


def generar(conn, semillas: list[str]) -> str:
    q = lambda sql: conn.execute(text(sql)).all()
    salida = [
        "/* Migración cero (línea base) generada por scripts/generar_linea_base.py.",
        "   En la base compartida se REGISTRA sin ejecutar (aplicar --marcar-linea-base);",
        "   en una base vacía se ejecuta. No se edita: una corrección es una migración nueva. */",
        "SET XACT_ABORT ON;",
        "GO",
    ]
    for (esquema,) in q(
        "SELECT name FROM sys.schemas WHERE schema_id BETWEEN 5 AND 16383 ORDER BY name"
    ):
        if esquema not in _ESQUEMAS_SISTEMA:
            salida += [
                f"IF SCHEMA_ID('{esquema}') IS NULL EXEC('CREATE SCHEMA {_q(esquema)}');",
                "GO",
            ]

    tablas = q(
        "SELECT t.object_id, s.name, t.name FROM sys.tables t JOIN sys.schemas s ON s.schema_id=t.schema_id "
        "WHERE t.is_ms_shipped=0 ORDER BY s.name, t.name"
    )
    for oid, esquema, tabla in tablas:
        cols = q(
            f"""SELECT c.name, ty.name, c.max_length, c.precision, c.scale, c.is_nullable, c.is_identity,
                       ic.seed_value, ic.increment_value, dc.name, dc.definition, cc.definition, c.is_rowguidcol
                FROM sys.columns c JOIN sys.types ty ON ty.user_type_id=c.user_type_id
                LEFT JOIN sys.identity_columns ic ON ic.object_id=c.object_id AND ic.column_id=c.column_id
                LEFT JOIN sys.default_constraints dc ON dc.object_id=c.default_object_id
                LEFT JOIN sys.computed_columns cc ON cc.object_id=c.object_id AND cc.column_id=c.column_id
                WHERE c.object_id={oid} ORDER BY c.column_id"""
        )
        lineas = []
        for (
            nombre,
            tipo,
            largo,
            prec,
            esc,
            nulo,
            ident,
            semilla,
            inc,
            df_nombre,
            df_def,
            calc,
            _,
        ) in cols:
            if calc is not None:
                lineas.append(f"    {_q(nombre)} AS {calc}")
                continue
            linea = f"    {_q(nombre)} {_tipo(tipo, largo, prec, esc)}"
            if ident:
                linea += f" IDENTITY({semilla},{inc})"
            linea += " NULL" if nulo else " NOT NULL"
            if df_def is not None:
                linea += f" CONSTRAINT {_q(df_nombre)} DEFAULT {df_def}"
            lineas.append(linea)
        for cnombre, es_pk, clustered, columnas in q(
            f"""SELECT i.name, i.is_primary_key, CASE WHEN i.type=1 THEN 1 ELSE 0 END,
                       STRING_AGG(QUOTENAME(c.name) + CASE WHEN ic.is_descending_key=1 THEN ' DESC' ELSE '' END, ', ')
                         WITHIN GROUP (ORDER BY ic.key_ordinal)
                FROM sys.indexes i JOIN sys.index_columns ic ON ic.object_id=i.object_id AND ic.index_id=i.index_id
                JOIN sys.columns c ON c.object_id=ic.object_id AND c.column_id=ic.column_id
                WHERE i.object_id={oid} AND (i.is_primary_key=1 OR i.is_unique_constraint=1) AND ic.key_ordinal>0
                GROUP BY i.name, i.is_primary_key, i.type"""
        ):
            tipo = "PRIMARY KEY" if es_pk else "UNIQUE"
            lineas.append(
                f"    CONSTRAINT {_q(cnombre)} {tipo} {'CLUSTERED' if clustered else 'NONCLUSTERED'} ({columnas})"
            )
        salida += [
            f"IF OBJECT_ID('{esquema}.{tabla}', 'U') IS NULL",
            f"CREATE TABLE {_q(esquema)}.{_q(tabla)} (",
            ",\n".join(lineas),
            ");",
            "GO",
        ]

    for esquema, tabla, nombre, unico, filtro, claves, incluidas in q(
        """SELECT s.name, t.name, i.name, i.is_unique, i.filter_definition,
                  STRING_AGG(CASE WHEN ic.key_ordinal>0 THEN QUOTENAME(c.name) + CASE WHEN ic.is_descending_key=1 THEN ' DESC' ELSE '' END END, ', ')
                    WITHIN GROUP (ORDER BY ic.key_ordinal),
                  STRING_AGG(CASE WHEN ic.is_included_column=1 THEN QUOTENAME(c.name) END, ', ')
           FROM sys.indexes i JOIN sys.tables t ON t.object_id=i.object_id JOIN sys.schemas s ON s.schema_id=t.schema_id
           JOIN sys.index_columns ic ON ic.object_id=i.object_id AND ic.index_id=i.index_id
           JOIN sys.columns c ON c.object_id=ic.object_id AND c.column_id=ic.column_id
           WHERE t.is_ms_shipped=0 AND i.is_primary_key=0 AND i.is_unique_constraint=0 AND i.type IN (1,2) AND i.name IS NOT NULL
           GROUP BY s.name, t.name, i.name, i.is_unique, i.filter_definition ORDER BY s.name, t.name, i.name"""
    ):
        sql = f"CREATE {'UNIQUE ' if unico else ''}INDEX {_q(nombre)} ON {_q(esquema)}.{_q(tabla)} ({claves})"
        if incluidas:
            sql += f" INCLUDE ({incluidas})"
        if filtro:
            sql += f" WHERE {filtro}"
        salida += [
            f"IF INDEXPROPERTY(OBJECT_ID('{esquema}.{tabla}'), '{nombre}', 'IndexID') IS NULL",
            sql + ";",
            "GO",
        ]

    for nombre, esquema, tabla, rs, rt, cols, rcols, borrar, actualizar, confiable in q(
        """SELECT fk.name, s.name, t.name, rs.name, rt.name,
                  STRING_AGG(QUOTENAME(pc.name), ', ') WITHIN GROUP (ORDER BY fkc.constraint_column_id),
                  STRING_AGG(QUOTENAME(rc.name), ', ') WITHIN GROUP (ORDER BY fkc.constraint_column_id),
                  fk.delete_referential_action_desc, fk.update_referential_action_desc, fk.is_not_trusted
           FROM sys.foreign_keys fk JOIN sys.tables t ON t.object_id=fk.parent_object_id JOIN sys.schemas s ON s.schema_id=t.schema_id
           JOIN sys.tables rt ON rt.object_id=fk.referenced_object_id JOIN sys.schemas rs ON rs.schema_id=rt.schema_id
           JOIN sys.foreign_key_columns fkc ON fkc.constraint_object_id=fk.object_id
           JOIN sys.columns pc ON pc.object_id=fkc.parent_object_id AND pc.column_id=fkc.parent_column_id
           JOIN sys.columns rc ON rc.object_id=fkc.referenced_object_id AND rc.column_id=fkc.referenced_column_id
           GROUP BY fk.name, s.name, t.name, rs.name, rt.name, fk.delete_referential_action_desc,
                    fk.update_referential_action_desc, fk.is_not_trusted ORDER BY s.name, t.name, fk.name"""
    ):
        acciones = ""
        if borrar != "NO_ACTION":
            acciones += f" ON DELETE {borrar.replace('_', ' ')}"
        if actualizar != "NO_ACTION":
            acciones += f" ON UPDATE {actualizar.replace('_', ' ')}"
        salida += [
            f"IF OBJECT_ID('{esquema}.{nombre}', 'F') IS NULL",
            (
                f"ALTER TABLE {_q(esquema)}.{_q(tabla)} WITH {'NOCHECK' if confiable else 'CHECK'} ADD CONSTRAINT {_q(nombre)} "
                f"FOREIGN KEY ({cols}) REFERENCES {_q(rs)}.{_q(rt)} ({rcols}){acciones};"
            ),
            "GO",
        ]

    for esquema, tabla, nombre, definicion, confiable in q(
        """SELECT s.name, t.name, cc.name, cc.definition, cc.is_not_trusted FROM sys.check_constraints cc
           JOIN sys.tables t ON t.object_id=cc.parent_object_id JOIN sys.schemas s ON s.schema_id=t.schema_id
           WHERE t.is_ms_shipped=0 ORDER BY s.name, t.name, cc.name"""
    ):
        salida += [
            f"IF OBJECT_ID('{esquema}.{nombre}', 'C') IS NULL",
            f"ALTER TABLE {_q(esquema)}.{_q(tabla)} WITH {'NOCHECK' if confiable else 'CHECK'} ADD CONSTRAINT {_q(nombre)} CHECK {definicion};",
            "GO",
        ]

    # Vistas, funciones y procedimientos antes que los disparadores (que pueden usarlos)
    for esquema, nombre, tipo, definicion in q(
        """SELECT s.name, o.name, o.type, m.definition FROM sys.sql_modules m JOIN sys.objects o ON o.object_id=m.object_id
           JOIN sys.schemas s ON s.schema_id=o.schema_id WHERE o.is_ms_shipped=0
           ORDER BY CASE o.type WHEN 'V' THEN 1 WHEN 'FN' THEN 2 WHEN 'IF' THEN 2 WHEN 'TF' THEN 2 WHEN 'P' THEN 3 ELSE 4 END,
                    s.name, o.name"""
    ):
        if definicion is None:
            salida += [
                f"-- {esquema}.{nombre} ({tipo.strip()}): definición cifrada o no visible; revisar a mano",
                "GO",
            ]
            continue
        salida += [
            f"IF OBJECT_ID('{esquema}.{nombre}') IS NULL",
            f"EXEC(N'{definicion.strip().replace(chr(39), chr(39) * 2)}');",
            "GO",
        ]

    for tabla in semillas:
        salida += _semilla(q, tabla)
    return "\n".join(salida) + "\n"


def _literal(valor: object) -> str:
    if valor is None:
        return "NULL"
    if isinstance(valor, bool):
        return "1" if valor else "0"
    if isinstance(valor, (int, float)):
        return str(valor)
    if isinstance(valor, (bytes, bytearray)):
        return "0x" + valor.hex()
    texto = valor.isoformat() if isinstance(valor, (date, time, datetime)) else str(valor)
    return "N'" + texto.replace("'", "''") + "'"


def _semilla(q, tabla: str) -> list[str]:
    esquema, nombre = tabla.split(".", 1)
    pk = [
        c
        for (c,) in q(
            f"""SELECT c.name FROM sys.indexes i JOIN sys.index_columns ic ON ic.object_id=i.object_id AND ic.index_id=i.index_id
                JOIN sys.columns c ON c.object_id=ic.object_id AND c.column_id=ic.column_id
                WHERE i.object_id=OBJECT_ID('{esquema}.{nombre}') AND i.is_primary_key=1 ORDER BY ic.key_ordinal"""
        )
    ]
    columnas = [
        c
        for (c,) in q(
            f"SELECT name FROM sys.columns WHERE object_id=OBJECT_ID('{esquema}.{nombre}') AND is_computed=0 ORDER BY column_id"
        )
    ]
    if not pk:
        return [f"-- {tabla}: sin clave primaria, semilla omitida", "GO"]
    filas = q(
        f"SELECT {', '.join(_q(c) for c in columnas)} FROM {_q(esquema)}.{_q(nombre)}"
    )
    if not filas:
        return []
    valores = ",\n".join(
        "    (" + ", ".join(_literal(v) for v in fila) + ")" for fila in filas
    )
    lista = ", ".join(_q(c) for c in columnas)
    on = " AND ".join(f"d.{_q(c)}=o.{_q(c)}" for c in pk)
    resto = [c for c in columnas if c not in pk]
    identidad = q(
        f"SELECT 1 FROM sys.identity_columns WHERE object_id=OBJECT_ID('{esquema}.{nombre}')"
    )
    lineas = [f"/* Semilla repetible de {tabla} (MERGE por clave primaria) */"]
    if identidad:
        lineas.append(f"SET IDENTITY_INSERT {_q(esquema)}.{_q(nombre)} ON;")
    lineas += [
        f"MERGE {_q(esquema)}.{_q(nombre)} AS d USING (VALUES\n{valores}\n) AS o ({lista}) ON {on}",
        (
            "WHEN MATCHED THEN UPDATE SET "
            + ", ".join(f"d.{_q(c)}=o.{_q(c)}" for c in resto)
        )
        if resto
        else "",
        f"WHEN NOT MATCHED THEN INSERT ({lista}) VALUES ({', '.join('o.' + _q(c) for c in columnas)});",
    ]
    if identidad:
        lineas.append(f"SET IDENTITY_INSERT {_q(esquema)}.{_q(nombre)} OFF;")
    return [x for x in lineas if x] + ["GO"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", choices=["cooperativa", "seguridad"], required=True)
    ap.add_argument(
        "--semillas",
        default="",
        help="tablas de referencia separadas por coma (Esquema.Tabla)",
    )
    a = ap.parse_args()
    odbc = getattr(get_settings(), f"migraciones_odbc_{a.base}").get_secret_value()
    if not odbc:
        print(f"falta MIGRACIONES_ODBC_{a.base.upper()}", file=sys.stderr)
        return 2
    engine = create_engine(URL.create("mssql+pyodbc", query={"odbc_connect": odbc}))
    with engine.connect() as conn:
        sys.stdout.write(
            generar(conn, [t.strip() for t in a.semillas.split(",") if t.strip()])
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
