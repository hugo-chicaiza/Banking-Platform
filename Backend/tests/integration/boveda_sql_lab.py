"""Laboratorio BOV opt-in, local SQLEXPRESS, nombre aleatorio y marca verificable.

No lee .env ni conecta las bases de negocio. Solo puede borrar la base que crea
esta instancia después de comprobar servidor, nombre y marca.
"""

import os
import platform
import re
from contextlib import closing
from pathlib import Path
from uuid import uuid4

import pyodbc
from sqlalchemy import create_engine

MARCA = "Banking-Platform.BOV.Local.Fictional.v1"
BACKEND = Path(__file__).resolve().parents[2]


class LaboratorioBoveda:
    def __init__(self):
        self.database = "CooperativaDB_BOV_Lab_" + uuid4().hex[:12]
        self.engine = None
        self.creada = False

    def verificar(self, raw, database, marca=True):
        with closing(raw.cursor()) as cursor:
            fila = cursor.execute("""
                SELECT CONVERT(nvarchar(128),SERVERPROPERTY('MachineName')),
                       CONVERT(nvarchar(128),SERVERPROPERTY('InstanceName')),
                       CONVERT(int,SERVERPROPERTY('EngineEdition')), DB_NAME()
            """).fetchone()
            if (
                fila is None
                or str(fila[0]).upper() != platform.node().upper()
                or fila[1] != "SQLEXPRESS"
                or fila[2] != 4
                or fila[3] != database
            ):
                raise RuntimeError("Destino fuera del laboratorio local SQLEXPRESS")
            if marca:
                valor = cursor.execute(
                    "SELECT CONVERT(nvarchar(128),value) FROM sys.extended_properties WHERE class=0 AND name='BOV_Local_Lab'"
                ).fetchval()
                if database != self.database or valor != MARCA:
                    raise RuntimeError("Base sin marca del laboratorio BOV")

    def abrir(self, database, marca=True, autocommit=False):
        if os.getenv("BOV_LOCAL_SQL") != "1" or database not in {
            "master",
            self.database,
        }:
            raise RuntimeError("Laboratorio BOV deshabilitado o base no permitida")
        raw = pyodbc.connect(
            "DRIVER={ODBC Driver 17 for SQL Server};SERVER=lpc:.\\SQLEXPRESS;"
            f"DATABASE={database};Trusted_Connection=yes;Encrypt=no;Connection Timeout=5;APP=BOV_Local_Lab;",
            autocommit=autocommit,
            timeout=5,
        )
        raw.timeout = 15
        try:
            self.verificar(raw, database, marca)
        except BaseException:
            raw.close()
            raise
        return raw

    def ejecutar_script(self, raw, path):
        for bloque in re.split(
            r"^GO\s*$", path.read_text(encoding="utf-8-sig"), flags=re.MULTILINE
        ):
            if bloque.strip():
                self.verificar(raw, self.database)
                with closing(raw.cursor()) as cursor:
                    cursor.execute(bloque)
                    while cursor.nextset():
                        pass

    def crear(self):
        if re.fullmatch(r"CooperativaDB_BOV_Lab_[a-f0-9]{12}", self.database) is None:
            raise RuntimeError("Nombre de laboratorio inválido")
        with (
            closing(self.abrir("master", marca=False, autocommit=True)) as raw,
            closing(raw.cursor()) as cursor,
        ):
            if cursor.execute(
                "SELECT 1 FROM sys.databases WHERE name=?", self.database
            ).fetchone():
                raise RuntimeError("La base ya existe; no se reutiliza")
            cursor.execute(f"CREATE DATABASE [{self.database}]")
            self.creada = True
        with closing(self.abrir(self.database, marca=False, autocommit=True)) as raw:
            with closing(raw.cursor()) as cursor:
                cursor.execute(
                    "EXEC sys.sp_addextendedproperty @name=N'BOV_Local_Lab', @value=?",
                    MARCA,
                )
            self.ejecutar_script(raw, Path(__file__).with_name("boveda_schema.sql"))
            migracion = BACKEND / "migrations/20261114_boveda_bov01_06.sql"
            self.ejecutar_script(raw, migracion)
            self.ejecutar_script(raw, migracion)  # También comprueba reejecución.
        self.engine = create_engine(
            "mssql+pyodbc://", creator=lambda: self.abrir(self.database)
        )
        return self.engine

    def borrar(self):
        if not self.creada:
            return
        if self.engine is not None:
            self.engine.dispose()
        with closing(self.abrir(self.database, autocommit=True)):
            pass  # Verifica la marca antes de conectar a master para borrar.
        with (
            closing(self.abrir("master", marca=False, autocommit=True)) as raw,
            closing(raw.cursor()) as cursor,
        ):
            cursor.execute(
                f"ALTER DATABASE [{self.database}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE"
            )
            cursor.execute(f"DROP DATABASE [{self.database}]")
