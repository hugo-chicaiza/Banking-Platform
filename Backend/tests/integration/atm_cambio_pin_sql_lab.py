"""Laboratorio ATM-06 opt-in. Solo SQL Server local y bases nuevas sinteticas.

Clona exclusivamente metadatos de coordinacion del laboratorio previamente
verificado. Nunca lee Settings, .env ni datos de las bases fuente. Conserva las
bases creadas; no tiene operaciones DROP DATABASE ni limpieza de historiales.
"""

import os
import re
from uuid import uuid4

import pyodbc
from sqlalchemy import create_engine

# El laboratorio emula el proceso de recuperacion, no el pool del servidor web.
# Configurar antes de la primera conexion para que invalidate cierre la sesion.
pyodbc.pooling = False

SERVER = "DESKTOP-OR5GE4R"
CONNECTION = "DRIVER={ODBC Driver 18 for SQL Server};SERVER=lpc:.;Trusted_Connection=yes;Encrypt=yes;TrustServerCertificate=yes;APP=ATM06_Local_Integration;DATABASE="


def abrir(base):
    cn = pyodbc.connect(CONNECTION + base + ";", autocommit=True, timeout=5)
    verificar(cn, base)
    cn.timeout = 10
    return cn


def verificar(cn, base):
    cur = cn.cursor()
    try:
        row = cur.execute(
            "SELECT CONVERT(nvarchar(128),SERVERPROPERTY('MachineName')), CONVERT(nvarchar(128),SERVERPROPERTY('ServerName')), CONVERT(nvarchar(128),SERVERPROPERTY('InstanceName')), CONVERT(int,SERVERPROPERTY('EngineEdition')), DB_NAME()"
        ).fetchone()
        if (
            row is None
            or row[0] != SERVER
            or row[1] != SERVER
            or row[2] is not None
            or row[3] == 5
            or row[4] != base
        ):
            raise RuntimeError("Destino SQL local no autorizado")
    finally:
        cur.close()


def ejecutar(cn, base, sql, params=()):
    verificar(cn, base)
    cur = cn.cursor()
    try:
        cur.execute(sql, params)
        while cur.nextset():
            pass
    finally:
        cur.close()


def identificador(nombre):
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", nombre) is None:
        raise RuntimeError("Identificador de metadatos no admitido")
    return "[" + nombre + "]"


def clonar_coordinacion(origen, destino, tabla):
    """Copia columnas, defaults, checks, claves, indices y triggers; cero filas."""
    source, target = abrir(origen), abrir(destino)
    try:
        cursor = source.cursor()
        columnas = cursor.execute(
            "SELECT c.name,t.name,c.max_length,c.precision,c.scale,c.is_nullable,c.collation_name,d.definition FROM sys.columns c JOIN sys.types t ON t.user_type_id=c.user_type_id LEFT JOIN sys.default_constraints d ON d.object_id=c.default_object_id WHERE c.object_id=OBJECT_ID(?) ORDER BY c.column_id",
            tabla,
        ).fetchall()
        if not columnas:
            raise RuntimeError("Falta la tabla fuente local verificada")
        defs = []
        for (
            nombre,
            tipo,
            largo,
            precision,
            escala,
            nullable,
            collation,
            default,
        ) in columnas:
            tipo_sql = tipo
            if tipo in ("varchar", "varbinary", "char"):
                tipo_sql += "(" + str(largo) + ")"
            elif tipo == "datetime2":
                tipo_sql += "(" + str(escala) + ")"
            elif tipo not in ("int", "bigint", "datetime", "uniqueidentifier", "bit"):
                raise RuntimeError("Tipo de columna inesperado")
            if collation:
                # COLLATE exige el nombre de intercalacion sin delimitadores.
                tipo_sql += " COLLATE " + identificador(collation)[1:-1]
            defs.append(
                identificador(nombre)
                + " "
                + tipo_sql
                + (" NULL" if nullable else " NOT NULL")
                + (" DEFAULT " + default if default else "")
            )
        ejecutar(target, destino, "CREATE TABLE " + tabla + " (" + ",".join(defs) + ")")
        indices = cursor.execute(
            "SELECT index_id,name,is_unique,is_primary_key,is_unique_constraint,filter_definition FROM sys.indexes WHERE object_id=OBJECT_ID(?) AND index_id>0",
            tabla,
        ).fetchall()
        for indice, nombre, unico, pk, uq, filtro in indices:
            cols = cursor.execute(
                "SELECT c.name,ic.is_included_column,ic.is_descending_key FROM sys.index_columns ic JOIN sys.columns c ON c.object_id=ic.object_id AND c.column_id=ic.column_id WHERE ic.object_id=OBJECT_ID(?) AND ic.index_id=? ORDER BY ic.key_ordinal,ic.index_column_id",
                tabla,
                indice,
            ).fetchall()
            keys = ",".join(
                identificador(n) + (" DESC" if desc else "")
                for n, incluido, desc in cols
                if not incluido
            )
            if pk or uq:
                sql = (
                    "ALTER TABLE "
                    + tabla
                    + " ADD CONSTRAINT "
                    + identificador(nombre)
                    + (" PRIMARY KEY" if pk else " UNIQUE")
                    + " ("
                    + keys
                    + ")"
                )
            else:
                sql = (
                    "CREATE "
                    + ("UNIQUE " if unico else "")
                    + "INDEX "
                    + identificador(nombre)
                    + " ON "
                    + tabla
                    + " ("
                    + keys
                    + ")"
                )
                included = [identificador(n) for n, inc, _ in cols if inc]
                if included:
                    sql += " INCLUDE (" + ",".join(included) + ")"
                if filtro:
                    sql += " WHERE " + filtro
            ejecutar(target, destino, sql)
        checks = cursor.execute(
            "SELECT name,definition FROM sys.check_constraints WHERE parent_object_id=OBJECT_ID(?)",
            tabla,
        ).fetchall()
        for nombre, definition in checks:
            ejecutar(
                target,
                destino,
                "ALTER TABLE "
                + tabla
                + " WITH CHECK ADD CONSTRAINT "
                + identificador(nombre)
                + " CHECK "
                + definition,
            )
        fks = cursor.execute(
            "SELECT f.name,pc.name,OBJECT_SCHEMA_NAME(fc.referenced_object_id),OBJECT_NAME(fc.referenced_object_id),rc.name FROM sys.foreign_keys f JOIN sys.foreign_key_columns fc ON fc.constraint_object_id=f.object_id JOIN sys.columns pc ON pc.object_id=fc.parent_object_id AND pc.column_id=fc.parent_column_id JOIN sys.columns rc ON rc.object_id=fc.referenced_object_id AND rc.column_id=fc.referenced_column_id WHERE f.parent_object_id=OBJECT_ID(?)",
            tabla,
        ).fetchall()
        for nombre, col, esquema, ref, refcol in fks:
            ejecutar(
                target,
                destino,
                "ALTER TABLE "
                + tabla
                + " WITH CHECK ADD CONSTRAINT "
                + identificador(nombre)
                + " FOREIGN KEY ("
                + identificador(col)
                + ") REFERENCES "
                + identificador(esquema)
                + "."
                + identificador(ref)
                + " ("
                + identificador(refcol)
                + ")",
            )
        triggers = cursor.execute(
            "SELECT m.definition FROM sys.triggers t JOIN sys.sql_modules m ON m.object_id=t.object_id WHERE t.parent_id=OBJECT_ID(?) AND t.is_disabled=0",
            tabla,
        ).fetchall()
        if len(triggers) != 1:
            raise RuntimeError("Trigger fuente inesperado")
        ejecutar(target, destino, triggers[0][0])
        cursor.close()
    finally:
        source.close()
        target.close()


def preparar():
    fuentes = {
        "seguridad": os.environ["ATM06_SCHEMA_SOURCE_SEG"],
        "cooperativa": os.environ["ATM06_SCHEMA_SOURCE_COOP"],
    }
    for tipo, nombre in fuentes.items():
        prefijo = "SeguridadDB" if tipo == "seguridad" else "CooperativaDB"
        if re.fullmatch(prefijo + r"_ATM06_[a-f0-9]{10}", nombre) is None:
            raise RuntimeError("Solo se admiten fuentes locales del laboratorio ATM06")
    sufijo = uuid4().hex[:10]
    bases = {
        "seguridad": "SeguridadDB_ATM06_Run_" + sufijo,
        "cooperativa": "CooperativaDB_ATM06_Run_" + sufijo,
    }
    print("ATM06 destinos locales nuevos, conservados incluso ante errores:", bases)
    master = abrir("master")
    try:
        for base in bases.values():
            cur = master.cursor()
            if cur.execute("SELECT DB_ID(?)", base).fetchval() is not None:
                raise RuntimeError("Base destino existente: detener")
            cur.close()
        for base in bases.values():
            ejecutar(master, "master", "CREATE DATABASE " + identificador(base))
    finally:
        master.close()
    for tipo, base in bases.items():
        cn = abrir(base)
        try:
            ejecutar(
                cn,
                base,
                "SET ANSI_NULLS ON; SET QUOTED_IDENTIFIER ON; SET ANSI_PADDING ON; SET ANSI_WARNINGS ON; SET ARITHABORT ON; SET CONCAT_NULL_YIELDS_NULL ON; SET NUMERIC_ROUNDABORT OFF;",
            )
            esquemas = (
                ("Tarjetas", "Seguridad", "Pruebas", "Auditoria", "Organizacion")
                if tipo == "seguridad"
                else ("Tarjeta", "Canal", "ATM")
            )
            for esquema in esquemas:
                ejecutar(cn, base, "CREATE SCHEMA " + identificador(esquema))
            if tipo == "seguridad":
                ejecutar(
                    cn,
                    base,
                    """
                    CREATE TABLE Tarjetas.TarjetaPIN (
                        ID_TarjetaPIN int IDENTITY PRIMARY KEY, ID_Tarjeta int NULL,
                        TienePINAsignado bit NOT NULL DEFAULT 0, FechaAsignacion datetime NULL,
                        FechaUltimoCambio datetime NULL, IntentosFallidos int NOT NULL DEFAULT 0,
                        Estado varchar(15) NOT NULL, FechaBloqueo datetime NULL, Motivo varchar(25) NULL,
                        PINOffset varchar(4) NULL, ReferenciaClavePVK varchar(32) NULL,
                        RequiereCambio bit NOT NULL DEFAULT 0,
                        CHECK (Estado IN ('Activo','Bloqueado','Inactivo')), CHECK (IntentosFallidos>=0));
                    CREATE UNIQUE INDEX UX_TarjetaPIN_ID_Tarjeta ON Tarjetas.TarjetaPIN(ID_Tarjeta) WHERE ID_Tarjeta IS NOT NULL;
                    CREATE TABLE Pruebas.PanFicticio(IdTarjeta int PRIMARY KEY, PanCifrado varbinary(max) NOT NULL, ReferenciaClave varchar(32) NOT NULL);
                    CREATE TABLE Seguridad.SesionesATMRevocadas(Jti uniqueidentifier PRIMARY KEY,FechaRevocacion datetime2(7) NOT NULL DEFAULT SYSUTCDATETIME(),FechaExpiracion datetime2(0) NOT NULL);
                    CREATE TABLE Organizacion.Usuarios(UsuarioID int PRIMARY KEY, RolesWorkOS varchar(200) NULL);
                    CREATE TABLE Auditoria.Auditoria(AuditoriaID int IDENTITY PRIMARY KEY,
                        UsuarioID int NULL REFERENCES Organizacion.Usuarios(UsuarioID),
                        NombreAccion varchar(100) NOT NULL,TablaAfectada varchar(100) NULL,
                        IDRegistro varchar(100) NULL,FechaHora datetime NOT NULL DEFAULT GETDATE(),
                        DireccionIP varchar(45) NULL,Descripcion varchar(500) NULL,
                        Resultado varchar(15) NOT NULL CHECK(Resultado IN ('Exitoso','Fallido')),
                        RolesWorkOS varchar(200) NULL);
                """,
                )
            else:
                ejecutar(
                    cn,
                    base,
                    """
                    CREATE TABLE Canal.Canal(IdCanal int PRIMARY KEY,CodigoCanal varchar(10) NOT NULL,Estado char(1) NOT NULL,RequiereTarjeta bit NOT NULL,RequierePin bit NOT NULL,RequiereTerminal bit NOT NULL);
                    CREATE TABLE ATM.ATM(IdATM int PRIMARY KEY,CodigoATM char(8) NOT NULL,TipoTerminal varchar(10) NOT NULL,Estado char(1) NOT NULL,IdCanal int NOT NULL REFERENCES Canal.Canal(IdCanal));
                    CREATE TABLE Tarjeta.Tarjeta(IdTarjeta int PRIMARY KEY,IdCliente int NOT NULL,IdCuenta int NOT NULL,NombresTitular varchar(250) NOT NULL,ApellidosTitular varchar(250) NOT NULL,PinAsignado bit NOT NULL,TipoTarjeta varchar(10) NOT NULL,FechaEmision date NOT NULL,FechaExpiracion date NOT NULL,Estado varchar(20) NOT NULL,HashNumeroTarjeta varbinary(32) NOT NULL);
                    CREATE TABLE Tarjeta.TarjetaHis(IdHistorial bigint IDENTITY PRIMARY KEY,IdTarjeta int NOT NULL REFERENCES Tarjeta.Tarjeta(IdTarjeta),TipoEvento varchar(20) NOT NULL,EstadoAnterior varchar(20) NULL,EstadoActual varchar(20) NULL,Descripcion varchar(500) NOT NULL,IdCanal int NULL REFERENCES Canal.Canal(IdCanal),RealizadoPor int NOT NULL,DireccionIP varchar(45) NULL,FechaEvento datetime2(7) NOT NULL DEFAULT SYSUTCDATETIME());
                    INSERT Canal.Canal VALUES(1,'ATM','A',1,1,1);
                    INSERT ATM.ATM VALUES(1,'ATM00001','ATM','A',1);
                """,
                )
                ejecutar(
                    cn,
                    base,
                    "CREATE TRIGGER Tarjeta.trg_TarjetaHis_Inmutable ON Tarjeta.TarjetaHis INSTEAD OF UPDATE,DELETE AS BEGIN SET NOCOUNT ON; IF EXISTS(SELECT 1 FROM deleted) THROW 57001,'Historial inmutable',1; END;",
                )
        finally:
            cn.close()
    clonar_coordinacion(
        fuentes["seguridad"], bases["seguridad"], "Tarjetas.CambioPINATMOperacion"
    )
    clonar_coordinacion(
        fuentes["cooperativa"], bases["cooperativa"], "Tarjeta.CambioPINATMAplicado"
    )
    return bases


class CursorLocal:
    def __init__(self, cursor, conexion):
        self.cursor_real, self.conexion = cursor, conexion

    def __getattr__(self, nombre):
        return getattr(self.cursor_real, nombre)

    def execute(self, *args, **kwargs):
        verificar(self.conexion.real, self.conexion.base)
        self.cursor_real.execute(*args, **kwargs)
        return self


class ConexionLocal:
    def __init__(self, base, fallos, tipo):
        self.real, self.base, self.fallos, self.tipo = abrir(base), base, fallos, tipo
        self.real.autocommit = False

    def __getattr__(self, nombre):
        return getattr(self.real, nombre)

    @property
    def timeout(self):
        return self.real.timeout

    @timeout.setter
    def timeout(self, valor):
        self.real.timeout = valor

    def cursor(self):
        return CursorLocal(self.real.cursor(), self)

    def commit(self):
        verificar(self.real, self.base)
        self.real.commit()
        if self.fallos.pop(self.tipo, False):
            raise pyodbc.OperationalError(
                "08S01", "Confirmacion de laboratorio perdida"
            )


def motor(base, fallos, tipo):
    return create_engine(
        "mssql+pyodbc://",
        creator=lambda: ConexionLocal(base, fallos, tipo),
        hide_parameters=True,
        pool_size=4,
        max_overflow=0,
    )
