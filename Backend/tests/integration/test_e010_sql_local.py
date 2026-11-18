"""Integration on a disposable local SQL Server database, never from .env."""

import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import Connection, create_engine, text
from sqlalchemy.exc import DBAPIError

from app.core.security import audit
from app.modules.catalogos import repository as catalogos
from app.modules.organizacion import repository as agencias
from app.modules.organizacion import service
from app.modules.organizacion.schemas import AgenciaCreate
from tests.sesion import usuario_con_roles

pytestmark = pytest.mark.skipif(
    os.getenv("E010_SQL_LOCAL") != "1", reason="requires the disposable local SQL lab"
)
MIGRACIONES = Path(__file__).resolve().parents[2] / "migrations"
ESQUEMA = """
CREATE TABLE Catalogo.Ciudad (
    IdCiudad int PRIMARY KEY, Nombre varchar(100), Provincia varchar(100)
);
INSERT Catalogo.Ciudad VALUES (1, 'Quito', 'Pichincha');
CREATE TABLE Organizacion.Agencia (
    IdAgencia char(3) CONSTRAINT PK_Agencia PRIMARY KEY,
    Codigo varchar(10) NOT NULL CONSTRAINT UQ_Agencia_Codigo UNIQUE,
    TipoAgencia varchar(10) NOT NULL CONSTRAINT CK_Agencia_Tipo
        CHECK (TipoAgencia IN ('Matriz', 'Sucursal')),
    Estado char(1) NOT NULL DEFAULT 'A' CONSTRAINT CK_Agencia_Estado
        CHECK (Estado IN ('A', 'I', 'C')),
    Telefono varchar(15), Direccion varchar(250),
    FechaCreacion datetime2 NOT NULL DEFAULT SYSDATETIME(),
    IdCiudad int NOT NULL CONSTRAINT FK_Agencia_Ciudad REFERENCES Catalogo.Ciudad,
    KeyAgencia varchar(64)
);
CREATE UNIQUE INDEX UX_Agencia_UnaMatriz ON Organizacion.Agencia(TipoAgencia)
    WHERE TipoAgencia = 'Matriz';
CREATE UNIQUE INDEX UX_Agencia_KeyAgencia ON Organizacion.Agencia(KeyAgencia)
    WHERE KeyAgencia IS NOT NULL;
INSERT Organizacion.Agencia (IdAgencia, Codigo, TipoAgencia, IdCiudad)
    VALUES ('017', 'SEDE', 'Matriz', 1);
CREATE TABLE Caja.JornadasCaja (IdAgencia char(3), Estado varchar(20));
CREATE TABLE Caja.CajaFisica (IdAgencia char(3), Estado bit);
CREATE TABLE Caja.CajerosAsignadosAgencia (IdAgencia char(3), Estado bit, FechaFin datetime2);
CREATE TABLE Boveda.Boveda (IdAgencia char(3), Estado char(1));
CREATE TABLE ATM.ATM (IdAgencia char(3), Estado char(1));
CREATE TABLE Cuentas.Cuenta (IdAgencia char(3), Estado varchar(20));
CREATE TABLE Credito.CreditoDesembolso (IdAgencia char(3), Estado varchar(20));
CREATE TABLE Auditoria.Auditoria (
    AuditoriaID int IDENTITY PRIMARY KEY, UsuarioID int, NombreAccion varchar(100) NOT NULL,
    TablaAfectada varchar(100), IDRegistro varchar(100), FechaHora datetime NOT NULL,
    DireccionIP varchar(45), Descripcion varchar(500), Resultado varchar(15) NOT NULL,
    RolesWorkOS varchar(200)
);
CREATE TABLE Organizacion.Usuarios (UsuarioID int PRIMARY KEY, RolesWorkOS varchar(200));
"""


@pytest.fixture
def lab() -> Iterator[Connection]:
    url = (
        "mssql+pyodbc://localhost/{base}?driver=ODBC+Driver+18+for+SQL+Server"
        "&TrustServerCertificate=yes"
    )
    nombre = "E010_Test_" + uuid4().hex
    admin = create_engine(url.format(base="master"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.exec_driver_sql(f"CREATE DATABASE [{nombre}]")
    engine = create_engine(url.format(base=nombre))
    try:
        with engine.connect() as conn:
            for esquema in (
                "Catalogo",
                "Organizacion",
                "Caja",
                "Boveda",
                "ATM",
                "Cuentas",
                "Credito",
                "Auditoria",
            ):
                conn.exec_driver_sql(f"CREATE SCHEMA {esquema}")
            conn.exec_driver_sql(ESQUEMA)
            conn.exec_driver_sql(
                "DECLARE @base sysname = DB_NAME(); "
                "EXEC sys.sp_set_session_context N'migration_database', @base;"
            )
            conn.commit()
            yield conn
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.exec_driver_sql(
                f"ALTER DATABASE [{nombre}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE; "
                f"DROP DATABASE [{nombre}];"
            )
        admin.dispose()


def _migrar(conn: Connection, direccion: str) -> None:
    for ruta in (
        f"cooperativa/202611181010_agencias_secuencia.{direccion}.sql",
        f"seguridad/202611181010_agencias_auditoria.{direccion}.sql",
    ):
        conn.exec_driver_sql((MIGRACIONES / ruta).read_text(encoding="ascii"))
    conn.commit()


def test_migraciones_y_flujo_en_sql(lab, monkeypatch):
    _migrar(lab, "up")
    _migrar(lab, "up")
    _migrar(lab, "down")
    _migrar(lab, "down")
    assert lab.scalar(text("SELECT OBJECT_ID('Organizacion.SeqAgenciaId')")) is None
    assert (
        lab.scalar(text("SELECT COL_LENGTH('Auditoria.Auditoria', 'DetalleJson')"))
        is None
    )
    lab.commit()
    _migrar(lab, "up")

    # Run through the real audit INSERT on the lab, using a separate transaction
    # at the same boundary as the application.
    def persistir(evento):
        with lab.begin():
            audit.registrar_en_transaccion(lab, evento)

    monkeypatch.setattr(audit, "_persistir", persistir)
    usuario = usuario_con_roles("ADMIN")
    datos = AgenciaCreate.model_validate(
        {
            "codigo": "SUC-018",
            "tipoAgencia": "Sucursal",
            "idCiudad": 1,
            "direccion": "A" * 250,
        }
    )
    creada = service.crear_agencia(lab, datos, 1, "127.0.0.1", "local", usuario)
    assert (creada.id_agencia, creada.estado) == ("018", "I")
    assert [f["Codigo"] for f in agencias.listar_agencias(lab, "I")] == ["SUC-018"]
    assert [f["codigo"] for f in catalogos.listar_agencias(lab)] == ["SEDE"]
    agencia = agencias.obtener_agencia(lab, "018")
    assert agencia is not None and agencia["Estado"] == "I"
    detalle, utc = lab.execute(
        text("""
        SELECT DetalleJson, DATEDIFF(second, FechaHora, SYSUTCDATETIME())
        FROM Auditoria.Auditoria WHERE NombreAccion = 'ORG_AGENCIA_CREADA'
    """)
    ).one()
    assert json.loads(detalle)["despues"]["direccion"] == "A" * 250
    assert abs(utc) < 30
    lab.rollback()

    with pytest.raises(HTTPException) as duplicada:
        service.crear_agencia(lab, datos, 1, None, "local", usuario)
    detalle_duplicada = cast(dict[str, object], duplicada.value.detail)
    assert detalle_duplicada["code"] == "CODIGO_DUPLICADO"

    service.cambiar_estado(lab, "018", "A", actor=usuario)
    lab.execute(text("INSERT Caja.JornadasCaja VALUES ('018', 'ABIERTA')"))
    lab.commit()
    with pytest.raises(HTTPException) as bloqueada:
        service.cambiar_estado(lab, "018", "I")
    detalle_bloqueada = cast(dict[str, object], bloqueada.value.detail)
    assert detalle_bloqueada["bloqueos"] == ["jornadas abiertas"]
    agencia = agencias.obtener_agencia(lab, "018")
    assert agencia is not None and agencia["Estado"] == "A"
    lab.rollback()
    with pytest.raises(DBAPIError, match="preserve la bitacora"):
        lab.exec_driver_sql(
            (
                MIGRACIONES / "seguridad/202611181010_agencias_auditoria.down.sql"
            ).read_text(encoding="ascii")
        )
    lab.rollback()
