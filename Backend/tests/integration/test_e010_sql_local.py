"""Integration on a disposable local SQL Server database, never from .env."""

import json
import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date
from pathlib import Path
from threading import Barrier
from typing import cast
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import Connection, Engine, create_engine, text
from sqlalchemy.exc import DBAPIError

from app.core.database.db import cooperativa
from app.modules.aprobaciones import router as api_aprobaciones
from app.modules.aprobaciones.auditoria import ContextoAuditoria
from app.modules.aprobaciones.identidad import Actor
from app.modules.aprobaciones.manejadores import registro_inicial
from app.modules.aprobaciones.registro import Objetivo
from app.modules.aprobaciones.relevo import entregar
from app.modules.aprobaciones.servicio import Servicio
from app.modules.auth import agencias_repository as asignaciones
from app.modules.auth import repository as usuarios
from app.modules.catalogos import repository as catalogos
from app.modules.organizacion import repository as agencias
from app.modules.organizacion import service
from app.modules.organizacion.aprobacion import CODIGO_BAJA
from app.modules.organizacion.router import router as agencias_router
from app.modules.organizacion.schemas import AgenciaCreate, AgenciaUpdate
from tests.sesion import simular_sesion, usuario_con_roles

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


def _ejecutar_migracion(conn: Connection, ruta: str) -> None:
    conn.exec_driver_sql((MIGRACIONES / ruta).read_text(encoding="utf8"))


@pytest.fixture(scope="module")
def lab() -> Iterator[tuple[Engine, Engine]]:
    url = (
        "mssql+pyodbc://localhost/{base}?driver=ODBC+Driver+18+for+SQL+Server"
        "&TrustServerCertificate=yes"
    )
    admin = create_engine(url.format(base="master"), isolation_level="AUTOCOMMIT")
    creadas = {}
    try:
        for tipo in ("cooperativa", "seguridad"):
            nombre = "E010_Test_" + uuid4().hex
            with admin.connect() as conn:
                conn.exec_driver_sql(f"CREATE DATABASE [{nombre}]")
            engine = create_engine(url.format(base=nombre), hide_parameters=True)
            creadas[nombre] = engine
            with engine.begin() as conn:
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
                for ruta in sorted((MIGRACIONES / tipo).glob("2026111808*.up.sql")):
                    _ejecutar_migracion(conn, f"{tipo}/{ruta.name}")
        coop, seg = creadas.values()
        yield coop, seg
    finally:
        for nombre, motor in creadas.items():
            motor.dispose()
            with admin.connect() as conn:
                conn.exec_driver_sql(
                    f"ALTER DATABASE [{nombre}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE; "
                    f"DROP DATABASE [{nombre}];"
                )
        admin.dispose()


ORG = "org_fixture_e010"
MAKER = Actor("user_maker", ORG, "Maker", 1, ("ADMIN",), frozenset(), ())
CHECKER = Actor(
    "user_checker",
    ORG,
    "Checker",
    2,
    ("SUPERVISOR",),
    frozenset({"agencias:aprobar"}),
    ("018", "019", "020", "021", "022", "023", "024"),
)
CONTEXTO = ContextoAuditoria("session_qa", "127.0.0.1", "e010-sql", agencia_actor="018")
HOY = date(2026, 11, 18)
USUARIO = replace(usuario_con_roles("ADMIN"), id_organizacion=ORG)


@pytest.fixture(scope="module")
def cola(lab):
    coop, seg = lab
    with coop.begin() as conn:
        conn.exec_driver_sql(
            "DECLARE @base sysname = DB_NAME(); "
            "EXEC sys.sp_set_session_context N'migration_database', @base;"
        )
        for direccion in ("up", "up", "down", "down"):
            for nombre in (
                "202611181010_agencias_secuencia",
                "202611181011_agencias_version",
            ):
                _ejecutar_migracion(conn, f"cooperativa/{nombre}.{direccion}.sql")
        assert (
            conn.scalar(text("SELECT OBJECT_ID('Organizacion.SeqAgenciaId')")) is None
        )
        assert (
            conn.scalar(text("SELECT COL_LENGTH('Organizacion.Agencia','VersionFila')"))
            is None
        )
        for nombre in (
            "202611181010_agencias_secuencia",
            "202611181011_agencias_version",
        ):
            _ejecutar_migracion(conn, f"cooperativa/{nombre}.up.sql")
    return Servicio(seg, coop, registro_inicial(), lambda sujeto, org: MAKER)


def _datos():
    return AgenciaCreate.model_validate(
        {
            "codigo": uuid4().hex[:10].upper(),
            "tipoAgencia": "Sucursal",
            "idCiudad": 1,
            "direccion": "A" * 250,
        }
    )


def _alta(cola, *, activar=True):
    with cola.cooperativa.connect() as conn:
        creada = service.crear_agencia(conn, _datos(), 1, "127.0.0.1", "local", USUARIO)
        if activar:
            service.cambiar_estado(conn, creada.id_agencia, "A", actor=USUARIO)
    return creada.id_agencia


def _estado(cola, id_):
    with cola.cooperativa.connect() as conn:
        return conn.scalar(
            text("SELECT Estado FROM Organizacion.Agencia WHERE IdAgencia=:id"),
            {"id": id_},
        )


def _solicitar(cola, id_):
    return cola.solicitar(
        MAKER,
        CODIGO_BAJA,
        Objetivo("Agencia", id_, id_),
        {"motivo": "Cierre"},
        HOY,
        CONTEXTO,
    )


def _error(error):
    return cast(dict[str, object], error.value.detail)


def test_alta_y_catalogo(cola):
    datos = _datos()
    with cola.cooperativa.connect() as conn:
        creada = service.crear_agencia(conn, datos, 1, "127.0.0.1", "local", USUARIO)
        assert creada.estado == "I"
        assert creada.codigo in {
            f["Codigo"] for f in agencias.listar_agencias(conn, "I")
        }
        assert creada.codigo not in {
            f["codigo"] for f in catalogos.listar_agencias(conn)
        }
        conn.rollback()
        with pytest.raises(HTTPException) as duplicada:
            service.crear_agencia(conn, datos, 1, None, "local", USUARIO)
        assert _error(duplicada)["code"] == "CODIGO_DUPLICADO"
    assert entregar(cola.cooperativa, cola.seguridad) > 0
    with cola.seguridad.connect() as conn:
        detalle, utc = conn.execute(
            text("""
            SELECT d.Contenido, DATEDIFF(second, d.FechaHoraUTC, SYSUTCDATETIME())
            FROM Auditoria.EventoDetalle d JOIN Auditoria.Auditoria a ON a.AuditoriaID=d.AuditoriaID
            WHERE a.NombreAccion='ORG_AGENCIA_CREADA' AND a.IDRegistro=:id
        """),
            {"id": creada.id_agencia},
        ).one()
        assert json.loads(detalle)["cambios"]["despues"]["direccion"] == "A" * 250
        assert abs(utc) < 30


def test_http_solicita_y_anota_autoaprobacion(cola, monkeypatch):
    agencia = _alta(cola)
    app = FastAPI()
    app.include_router(agencias_router, prefix="/api/v1")
    app.include_router(api_aprobaciones.router, prefix="/api/v1")
    proveedor_actual = api_aprobaciones.actual
    proveedor_cola = api_aprobaciones.servicio
    app.dependency_overrides[cooperativa] = cola.cooperativa.connect
    app.dependency_overrides[proveedor_actual] = lambda: MAKER
    app.dependency_overrides[proveedor_cola] = lambda: cola
    monkeypatch.setattr(api_aprobaciones, "actual", lambda _: MAKER)
    monkeypatch.setattr(api_aprobaciones, "servicio", lambda: cola)
    simular_sesion(app, USUARIO)
    cliente = TestClient(app)
    directa = cliente.post(
        "/api/v1/aprobaciones",
        json={
            "codigoTransaccion": CODIGO_BAJA,
            "tipoObjetivo": "Agencia",
            "idObjetivo": agencia,
            "idAgencia": agencia,
            "contenido": {},
        },
    )
    assert (directa.status_code, directa.json()["code"]) == (403, "SIN_PERMISO")
    r = cliente.patch(
        f"/api/v1/organizacion/agencias/{agencia}/estado", json={"estado": "I"}
    )
    assert r.status_code == 202, r.text
    id_ = r.json()["idSolicitud"]
    assert _estado(cola, agencia) == "A"
    r = cliente.post(f"/api/v1/aprobaciones/{id_}/aprobar", json={})
    assert (r.status_code, r.json()["code"]) == (403, "APROBADOR_ES_SOLICITANTE")
    with cola.seguridad.connect() as conn:
        assert (
            conn.scalar(
                text("""
            SELECT COUNT(*) FROM Auditoria.EventoPendiente
            WHERE CodigoEvento='APR_AUTOAPROBACION_INTENTO'
            AND JSON_VALUE(Contenido,'$.idObjetivo')=:id
        """),
                {"id": str(id_)},
            )
            == 1
        )
    checker = replace(CHECKER, agencias=(agencia,))
    app.dependency_overrides[proveedor_actual] = lambda: checker
    simular_sesion(app, replace(usuario_con_roles("SUPERVISOR"), id_agencia=agencia))
    r = cliente.post(f"/api/v1/aprobaciones/{id_}/aprobar", json={})
    assert r.json() == {"idSolicitud": id_, "estado": "Ejecutada"}
    assert _estado(cola, agencia) == "I"
    with cola.cooperativa.connect() as conn:
        assert not usuarios.agencia_activa(conn, agencia)
        assert any(a["id_agencia"] == agencia for a in asignaciones.agencias(conn))
        assert all(a["id_agencia"] != agencia for a in catalogos.listar_agencias(conn))


@pytest.mark.parametrize(
    "dependencia", ["Caja.JornadasCaja", "Caja.CajaFisica", "Boveda.Boveda"]
)
def test_revalida_operaciones_creadas_despues_de_solicitar(cola, dependencia):
    agencia = _alta(cola)
    id_ = _solicitar(cola, agencia)
    sentencias = {
        "Caja.JornadasCaja": "INSERT Caja.JornadasCaja VALUES (:id, 'ABIERTA')",
        "Caja.CajaFisica": "INSERT Caja.CajaFisica VALUES (:id, 1)",
        "Boveda.Boveda": "INSERT Boveda.Boveda VALUES (:id, 'A')",
    }
    with cola.cooperativa.begin() as conn:
        conn.execute(text(sentencias[dependencia]), {"id": agencia})
    with pytest.raises(HTTPException) as bloqueada:
        cola.aprobar(replace(CHECKER, agencias=(agencia,)), id_, None, CONTEXTO)
    assert _error(bloqueada)["code"] == "AGENCIA_CON_OPERACION"
    assert _error(bloqueada)["bloqueos"]
    assert _estado(cola, agencia) == "A"


def test_concurrencia_reintento_y_relevo_idempotente(cola):
    agencia = _alta(cola)
    id_ = _solicitar(cola, agencia)
    with pytest.raises(HTTPException) as duplicada:
        _solicitar(cola, agencia)
    assert _error(duplicada)["code"] == "SOLICITUD_YA_PENDIENTE"
    checker = replace(CHECKER, agencias=(agencia,))
    with pytest.raises(HTTPException) as denegada:
        cola.aprobar(replace(checker, permisos=frozenset()), id_, None, CONTEXTO)
    assert _error(denegada)["code"] == "SIN_PERMISO"
    with pytest.raises(HTTPException) as fuera:
        cola.aprobar(replace(checker, agencias=()), id_, None, CONTEXTO)
    assert _error(fuera)["code"] == "SOLICITUD_NO_ENCONTRADA"
    with pytest.raises(HTTPException) as misma_persona:
        cola.aprobar(replace(checker, id_interno=MAKER.id_interno), id_, None, CONTEXTO)
    assert _error(misma_persona)["code"] == "APROBADOR_ES_SOLICITANTE"
    barrera = Barrier(2, timeout=10)

    def aprobar(actor):
        barrera.wait()
        try:
            return cola.aprobar(actor, id_, None, CONTEXTO)["estado"]
        except HTTPException as exc:
            return cast(dict[str, object], exc.detail)["code"]

    with ThreadPoolExecutor(max_workers=2) as grupo:
        resultados = list(
            grupo.map(
                aprobar, [checker, replace(checker, sujeto="user_otro", id_interno=3)]
            )
        )
    assert set(resultados) == {"Ejecutada", "SOLICITUD_NO_PENDIENTE"}
    assert _estado(cola, agencia) == "I"
    assert cola.ejecutar(id_, ORG, None, CONTEXTO)["estado"] == "Ejecutada"
    assert entregar(cola.cooperativa, cola.seguridad) > 0
    assert entregar(cola.cooperativa, cola.seguridad) == 0
    with cola.seguridad.connect() as conn:
        detalle = conn.execute(
            text("""
            SELECT d.Contenido FROM Auditoria.EventoDetalle d
            JOIN Auditoria.Auditoria a ON a.AuditoriaID=d.AuditoriaID
            WHERE a.NombreAccion='ORG_AGENCIA_ESTADO' AND a.TablaAfectada='Organizacion.Agencia'
            AND a.IDRegistro=:agencia AND JSON_VALUE(d.Contenido,'$.idSolicitud')=:id
        """),
            {"agencia": agencia, "id": str(id_)},
        ).scalar_one()
    contenido = json.loads(detalle)
    assert contenido["roles"] == ["SUPERVISOR"]
    assert contenido["cambios"]["antes"]["estado"] == "A"
    assert contenido["cambios"]["despues"]["estado"] == "I"
    assert contenido["cambios"]["solicitante"] == MAKER.sujeto
    assert contenido["cambios"]["aprobador"] in {CHECKER.sujeto, "user_otro"}


def test_reversion_y_recuperacion_si_falla_evidencia(cola):
    agencia = _alta(cola)
    id_ = _solicitar(cola, agencia)
    inactiva = _alta(cola, activar=False)
    with cola.cooperativa.begin() as conn:
        conn.exec_driver_sql("""
            CREATE TRIGGER Auditoria.trg_QA_Falla ON Auditoria.EventoPendiente AFTER INSERT
            AS BEGIN SET NOCOUNT ON; THROW 50000, 'Fallo simulado de escritura', 1; END;
        """)
    try:
        datos = _datos()
        with cola.cooperativa.connect() as conn:
            with pytest.raises(HTTPException):
                service.crear_agencia(conn, datos, 1, None, "local", USUARIO)
            assert datos.codigo not in {
                a["Codigo"] for a in agencias.listar_agencias(conn, None)
            }
            conn.rollback()
            with pytest.raises(HTTPException):
                service.actualizar_agencia(
                    conn,
                    agencia,
                    AgenciaUpdate.model_validate({"telefono": "123456"}),
                    1,
                    None,
                    "local",
                    USUARIO,
                )
            fila = agencias.obtener_agencia(conn, agencia)
            assert fila is not None and fila["Telefono"] is None
            conn.rollback()
            with pytest.raises(DBAPIError):
                service.cambiar_estado(conn, inactiva, "A", actor=USUARIO)
            assert _estado(cola, inactiva) == "I"
        with pytest.raises(HTTPException) as fallo:
            cola.aprobar(replace(CHECKER, agencias=(agencia,)), id_, None, CONTEXTO)
        assert _error(fallo)["code"] == "APROBACION_PENDIENTE_RECUPERACION"
        assert _estado(cola, agencia) == "A"
    finally:
        with cola.cooperativa.begin() as conn:
            conn.exec_driver_sql("DROP TRIGGER Auditoria.trg_QA_Falla")
    assert (
        cola.ejecutar(id_, ORG, None, ContextoAuditoria(canal="SISTEMA"))["estado"]
        == "Ejecutada"
    )
    assert _estado(cola, agencia) == "I"
    with cola.cooperativa.connect() as conn:
        detalle = conn.execute(
            text("""
            SELECT Contenido FROM Auditoria.EventoPendiente WHERE CodigoEvento='ORG_AGENCIA_ESTADO'
              AND JSON_VALUE(Contenido,'$.idSolicitud')=:id
        """),
            {"id": str(id_)},
        ).scalar_one()
    evidencia = json.loads(detalle)
    assert evidencia["roles"] == ["SUPERVISOR"]
    assert evidencia["sesion"] == CONTEXTO.sesion
    assert evidencia["agenciaActor"] == CONTEXTO.agencia_actor


def test_version_rechaza_edicion_y_reversion(cola):
    agencia = _alta(cola)
    id_ = _solicitar(cola, agencia)
    with cola.cooperativa.begin() as conn:
        conn.execute(
            text(
                "UPDATE Organizacion.Agencia SET Telefono='123456' WHERE IdAgencia=:id"
            ),
            {"id": agencia},
        )
        conn.execute(
            text("UPDATE Organizacion.Agencia SET Telefono=NULL WHERE IdAgencia=:id"),
            {"id": agencia},
        )
    with pytest.raises(HTTPException) as desactualizada:
        cola.aprobar(replace(CHECKER, agencias=(agencia,)), id_, None, CONTEXTO)
    assert _error(desactualizada)["code"] == "SOLICITUD_DESACTUALIZADA"
    assert _estado(cola, agencia) == "A"


def test_ediciones_concurrentes_conservan_campos_e_invalidan_baja(cola):
    agencia = _alta(cola)
    id_ = _solicitar(cola, agencia)
    barrera = Barrier(2, timeout=10)

    def editar(cambios):
        with cola.cooperativa.connect() as conn:
            barrera.wait()
            service.actualizar_agencia(
                conn,
                agencia,
                AgenciaUpdate.model_validate(cambios),
                1,
                None,
                "local",
                USUARIO,
            )

    with ThreadPoolExecutor(max_workers=2) as grupo:
        list(grupo.map(editar, [{"telefono": "123456"}, {"direccion": "Calle QA"}]))

    with cola.cooperativa.connect() as conn:
        fila = agencias.obtener_agencia(conn, agencia)
        assert fila is not None
        assert (fila["Telefono"], fila["Direccion"]) == ("123456", "Calle QA")

    with pytest.raises(HTTPException) as desactualizada:
        cola.aprobar(replace(CHECKER, agencias=(agencia,)), id_, None, CONTEXTO)
    assert _error(desactualizada)["code"] == "SOLICITUD_DESACTUALIZADA"
    assert _estado(cola, agencia) == "A"


def test_version_agencia_es_hexadecimal_y_cambia_con_edicion(cola):
    agencia = _alta(cola)
    with cola.cooperativa.connect() as conn:
        anterior = agencias.version_agencia(conn, agencia)
        assert isinstance(anterior, str) and len(anterior) == 16
        assert all(c in "0123456789ABCDEF" for c in anterior)
        assert anterior == agencias.version_agencia(conn, agencia)
        conn.rollback()
        service.actualizar_agencia(
            conn,
            agencia,
            AgenciaUpdate.model_validate({"telefono": "123456"}),
            1,
            None,
            "local",
            USUARIO,
        )
        posterior = agencias.version_agencia(conn, agencia)
        assert isinstance(posterior, str) and len(posterior) == 16
        assert all(c in "0123456789ABCDEF" for c in posterior)
        assert posterior != anterior
