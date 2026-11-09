"""Laboratorio SQL local opt-in. Nunca usa .env para elegir destinos de escritura."""

import os
import re
from contextlib import closing
from typing import Any

import pyodbc
from sqlalchemy import URL, create_engine

SERVER = "DESKTOP-OR5GE4R"
COOP = "CooperativaDB_ATM02_Lab"
SEG = "SeguridadDB_ATM02_Lab"
DATABASES = (COOP, SEG)
MARKER = "Banking-Platform.ATM02.Local.Fictional.v1"


def verificar(raw, database: str, *, marker: bool = True) -> None:
    with closing(raw.cursor()) as cursor:
        row = cursor.execute("""
            SELECT CONVERT(nvarchar(128),SERVERPROPERTY('ServerName')),
                   CONVERT(nvarchar(128),SERVERPROPERTY('MachineName')),
                   CONVERT(nvarchar(128),SERVERPROPERTY('InstanceName')),
                   CONVERT(int,SERVERPROPERTY('EngineEdition')), DB_NAME()
        """).fetchone()
        if (
            row is None
            or str(row[0]).upper() != SERVER
            or str(row[1]).upper() != SERVER
            or row[2] not in (None, "MSSQLSERVER")
            or row[3] == 5
            or row[4] != database
        ):
            raise RuntimeError("Destino SQL fuera del laboratorio autorizado")
        if marker:
            value = cursor.execute("""
                SELECT CONVERT(nvarchar(128),value) FROM sys.extended_properties
                WHERE class=0 AND name='ATM02_Lab'
            """).fetchval()
            if database not in DATABASES or value != MARKER:
                raise RuntimeError("Base sin marca de laboratorio autorizado")


def conectar(database: str, *, bootstrap: bool = False, autocommit: bool = False):
    if database not in (*DATABASES, "master") or (
        database == "master" and not bootstrap
    ):
        raise RuntimeError("Base SQL no autorizada")
    if os.environ.get("ATM02_LOCAL_SQL_ENABLED") != "1":
        raise RuntimeError("Laboratorio local deshabilitado")
    drivers = pyodbc.drivers()
    driver = next(
        (
            d
            for d in ("ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server")
            if d in drivers
        ),
        None,
    )
    if driver is None:
        raise RuntimeError("Controlador SQL local no disponible")
    raw = pyodbc.connect(
        f"DRIVER={{{driver}}};SERVER=lpc:.;DATABASE={database};"
        "Trusted_Connection=yes;Encrypt=yes;TrustServerCertificate=yes;"
        "Connection Timeout=5;APP=ATM02_Local_Lab;",
        autocommit=autocommit,
        timeout=5,
    )
    raw.timeout = 15
    try:
        verificar(raw, database, marker=not bootstrap)
    except BaseException:
        raw.close()
        raise
    return raw


def crear_bases() -> None:
    if os.environ.get("ATM02_LOCAL_CREATE") != "1":
        raise RuntimeError("Creación no autorizada")
    with (
        closing(conectar("master", bootstrap=True, autocommit=True)) as raw,
        closing(raw.cursor()) as cursor,
    ):
        existentes = cursor.execute(
            "SELECT name FROM sys.databases WHERE name IN (?,?)", *DATABASES
        ).fetchall()
        if existentes:
            raise RuntimeError(
                "Ya existe una base del laboratorio; detener y consultar"
            )
        for database in DATABASES:
            verificar(raw, "master", marker=False)
            cursor.execute(
                f"CREATE DATABASE [{database}] COLLATE SQL_Latin1_General_CP1_CI_AS"
            )
            verificar(raw, "master", marker=False)
            cursor.execute(
                f"ALTER DATABASE [{database}] SET READ_COMMITTED_SNAPSHOT ON"
            )
            verificar(raw, "master", marker=False)
            cursor.execute(
                f"ALTER DATABASE [{database}] SET ALLOW_SNAPSHOT_ISOLATION ON"
            )
    for database in DATABASES:
        with closing(conectar(database, bootstrap=True, autocommit=True)) as raw:
            verificar(raw, database, marker=False)
            with closing(raw.cursor()) as cursor:
                cursor.execute(
                    "EXEC sys.sp_addextendedproperty @name=N'ATM02_Lab', @value=?",
                    MARKER,
                )


class CursorLocal:
    def __init__(self, raw, cursor, database):
        self._raw, self._cursor, self._database = raw, cursor, database

    def execute(self, sql, *args):
        verificar(self._raw, self._database)
        self._validar(sql)
        if re.search(
            r"(?:^|;)\s*(USE|CREATE\s+DATABASE|ALTER\s+DATABASE|DROP\s+DATABASE)\b",
            sql,
            re.IGNORECASE,
        ):
            raise RuntimeError("Cambio de destino SQL prohibido")
        self._cursor.execute(sql, *args)
        return self

    def executemany(self, sql, params):
        verificar(self._raw, self._database)
        self._validar(sql)
        if re.search(
            r"(?:^|;)\s*(USE|CREATE\s+DATABASE|ALTER\s+DATABASE|DROP\s+DATABASE)\b",
            sql,
            re.IGNORECASE,
        ):
            raise RuntimeError("Cambio de destino SQL prohibido")
        self._cursor.executemany(sql, params)
        return self

    @staticmethod
    def _validar(sql):
        if re.search(
            r"\b(?:CatBank|PetroleumDW|master|CooperativaDB|SeguridadDB)\]?\s*\.",
            sql,
            re.IGNORECASE,
        ):
            raise RuntimeError("Referencia a otra base prohibida")
        if re.search(
            r"\b(?:OPENROWSET|OPENDATASOURCE|OPENQUERY|xp_cmdshell|sp_addlinkedserver)\b",
            sql,
            re.IGNORECASE,
        ):
            raise RuntimeError("Acceso externo prohibido")

    def close(self):
        self._cursor.close()

    def __getattr__(self, name):
        return getattr(self._cursor, name)


class ConexionLocal:
    def __init__(self, raw, database):
        self._raw, self._database = raw, database

    @property
    def timeout(self):
        return self._raw.timeout

    @timeout.setter
    def timeout(self, value):
        self._raw.timeout = value

    def cursor(self):
        return CursorLocal(self._raw, self._raw.cursor(), self._database)

    def commit(self):
        verificar(self._raw, self._database)
        self._raw.commit()

    def __getattr__(self, name):
        return getattr(self._raw, name)


def motor(database: str, **kwargs: Any):
    return create_engine(
        URL.create("mssql+pyodbc"),
        creator=lambda: ConexionLocal(conectar(database), database),
        hide_parameters=True,
        pool_pre_ping=True,
        **kwargs,
    )
