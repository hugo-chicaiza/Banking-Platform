"""Cola y tarjetas en LocalDB descartable. WorkOS, custodia y sobre son ficticios."""

import os
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pyodbc
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import URL, create_engine, text
from sqlalchemy.exc import DBAPIError

from app.core.api.errors import problema
from app.modules.aprobaciones import router
from app.modules.aprobaciones.auditoria import ContextoAuditoria
from app.modules.aprobaciones.identidad import Actor
from app.modules.aprobaciones.manejadores import registro_inicial
from app.modules.aprobaciones.servicio import Servicio
from app.modules.tarjetas import aprobacion, service
from scripts.recuperar_solicitudes_tarjetas_e610 import recuperar
from tests.sesion import USUARIO, simular_sesion
from tests.tarjetas_hsm import instalar

pytestmark = pytest.mark.skipif(
    os.getenv("E610_LOCALDB") != "1", reason="Requiere SQL Server LocalDB"
)
_MIGRACIONES = Path(__file__).resolve().parents[2] / "migrations"
_DSN = r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=(localdb)\MSSQLLocalDB;Trusted_Connection=yes;Encrypt=no;"


def _migrar(cur, base, archivo):
    cur.execute("EXEC sys.sp_set_session_context N'migration_database', ?", base)
    cur.execute((_MIGRACIONES / archivo).read_text(encoding="utf-8"))
    while cur.nextset():
        pass


@pytest.fixture
def bases():
    sufijo = uuid4().hex
    coop, seg = f"LabTarjetaCoop_{sufijo}", f"LabTarjetaSeg_{sufijo}"
    motores = []
    creadas = []
    with pyodbc.connect(_DSN + "DATABASE=master;", autocommit=True, timeout=5) as conn:
        cur = conn.cursor()
        try:
            for base in (coop, seg):
                cur.execute(f"CREATE DATABASE [{base}]")
                creadas.append(base)
                motores.append(
                    create_engine(
                        URL.create(
                            "mssql+pyodbc",
                            query={"odbc_connect": _DSN + f"DATABASE={base};"},
                        ),
                        hide_parameters=True,
                    )
                )
            cur.execute(f"USE [{coop}]")
            for esquema in ("Tarjeta", "Canal"):
                cur.execute(f"CREATE SCHEMA {esquema}")
            cur.execute("""
                CREATE TABLE Tarjeta.Tarjeta (
                    IdTarjeta int PRIMARY KEY, TokenTarjeta varchar(64), NumeroEnmascarado varchar(19),
                    TipoTarjeta varchar(10), NombreTarjeta nvarchar(26), IdCliente int, IdCuenta int, IdProducto int,
                    Estado varchar(20), EsExtension bit, IdTarjetaTitular int NULL, PinAsignado bit,
                    FechaSolicitud date, FechaResolucion datetime2 NULL, FechaEmision date, FechaExpiracion date,
                    IdAgencia char(3), CreadoPor int, MotivoEstado varchar(30) NULL,
                    EntregaVerificadaEn datetime2 NULL, SobreDescargadoEn datetime2 NULL
                );
                CREATE TABLE Tarjeta.EnviosTarjeta (IdTarjeta int, RequiereEnvio bit, CodigoSeguimiento varchar(64), DespachadoEn datetime2);
                CREATE TABLE Tarjeta.TransicionEstado (EstadoOrigen varchar(20), EstadoDestino varchar(20));
                CREATE TABLE Tarjeta.TarjetaHis (
                    IdHistorial int IDENTITY PRIMARY KEY, IdTarjeta int, TipoEvento varchar(20),
                    EstadoAnterior varchar(20), EstadoActual varchar(20), Descripcion nvarchar(500),
                    IdCanal int, RealizadoPor int NOT NULL, DireccionIP varchar(45)
                );
                CREATE TABLE Canal.Canal (IdCanal int, CodigoCanal varchar(10));
                INSERT Canal.Canal VALUES (1,'VENT');
                INSERT Tarjeta.TransicionEstado VALUES ('Solicitada','Aprobada'),('Aprobada','Generada'),('Solicitada','Anulada');
                INSERT Tarjeta.Tarjeta
                SELECT Id,'tok_qa','5000 00** **** 1234','Debito',N'CLIENTE QA',2,Id,4,'Solicitada',0,NULL,0,
                       '2026-11-25',NULL,'2026-11-25','2031-11-25','001',11,NULL,NULL,NULL
                FROM (VALUES (321),(322),(323)) AS f(Id);
            """)
            _migrar(cur, coop, "cooperativa/202611180802_aprobaciones_entrega.up.sql")
            for sufijo_sql in ("up", "down", "up", "up"):
                _migrar(
                    cur,
                    coop,
                    f"cooperativa/202611261600_tarjetas_aprobaciones.{sufijo_sql}.sql",
                )
            cur.execute(f"USE [{seg}]")
            cur.execute("CREATE SCHEMA Organizacion")
            cur.execute(
                "CREATE TABLE Organizacion.Usuarios (UsuarioID int PRIMARY KEY, KeyUsuario varchar(64), Estado varchar(12))"
            )
            cur.execute(
                "INSERT Organizacion.Usuarios VALUES (11, 'user_solicitante_qa', 'Activo')"
            )
            for archivo in (
                "seguridad/202611180800_aprobaciones_catalogo.up.sql",
                "seguridad/202611180801_aprobaciones_solicitudes.up.sql",
                "cooperativa/202611180802_aprobaciones_entrega.up.sql",
                "seguridad/202611261600_tarjetas_aprobaciones.up.sql",
                "seguridad/202611261600_tarjetas_aprobaciones.down.sql",
                "seguridad/202611261600_tarjetas_aprobaciones.up.sql",
                "seguridad/202611261600_tarjetas_aprobaciones.up.sql",
            ):
                _migrar(cur, seg, archivo)
            yield tuple(motores)
        finally:
            for motor in motores:
                motor.dispose()
            cur.execute("USE master")
            for base in reversed(creadas):
                cur.execute(
                    f"ALTER DATABASE [{base}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE"
                )
                cur.execute(f"DROP DATABASE [{base}]")


def test_recupera_aprueba_y_rechaza_las_tarjetas_ficticias(bases, monkeypatch):
    coop, seg = bases
    org = "org_tarjetas_qa"
    titular = Actor(
        "user_solicitante_qa",
        org,
        "Solicitante QA",
        11,
        ("ASESOR",),
        frozenset(),
        ("001",),
    )
    supervisor = Actor(
        "user_supervisor_qa",
        org,
        "Supervisor QA",
        12,
        ("SUPERVISOR",),
        frozenset(),
        ("001", "002"),
    )
    personas = {a.sujeto: a for a in (titular, supervisor)}
    cola = Servicio(seg, coop, registro_inicial(), lambda sujeto, _: personas[sujeto])
    memoria = instalar(monkeypatch)
    memoria.custodiar(321)
    sobres = []

    def preparar_sobre(id_tarjeta, _pin, origen):
        sobres.append((id_tarjeta, origen))
        return "qa"

    monkeypatch.setattr(
        service.sobre_pin,
        "obtener_servicio",
        lambda: SimpleNamespace(preparar=preparar_sobre),
    )
    monkeypatch.setattr(aprobacion, "get_engine", lambda _: seg)
    monkeypatch.setattr(
        "app.modules.aprobaciones.lecturas.general.valor", lambda *a: 30
    )
    app = FastAPI()
    app.include_router(router.router, prefix="/api/v1")
    app.dependency_overrides[router.servicio] = lambda: cola

    def iniciar(actor, agencia="001"):
        app.dependency_overrides[router.actual] = lambda: actor
        simular_sesion(
            app,
            replace(
                USUARIO,
                id_usuario=actor.sujeto,
                id_organizacion=org,
                id_interno=actor.id_interno,
                id_agencia=agencia,
                roles=actor.roles,
                permisos=tuple(actor.permisos),
            ),
        )

    primera, segunda = [recuperar(cola, tarjeta, org) for tarjeta in (321, 322)]
    assert [recuperar(cola, tarjeta, org) for tarjeta in (321, 322)] == [
        primera,
        segunda,
    ]
    ruta = "/api/v1/aprobaciones"
    iniciar(titular)
    with TestClient(app) as client:
        propias = client.get(ruta, params={"bandeja": "mias"}).json()["items"]
        assert {f["idObjetivo"] for f in propias} == {"321", "322"}
        assert all(
            f["idAgencia"] == "001"
            and f["solicitante"]["idInterno"] == 11
            and not f["puedeCancelar"]
            for f in propias
        )
        assert (
            client.post(f"{ruta}/{primera}/aprobar", json={}).json()["code"]
            == "APROBADOR_ES_SOLICITANTE"
        )

        iniciar(
            replace(
                supervisor,
                roles=("ADMIN",),
                permisos=frozenset({"tar-solicitar:aprobar"}),
            )
        )
        assert client.get(ruta).json()["total"] == 0
        assert client.get(f"{ruta}/{primera}").status_code == 404
        assert client.post(f"{ruta}/{primera}/aprobar", json={}).status_code == 404
        assert (
            client.post(
                f"{ruta}/{segunda}/rechazar", json={"comentario": "Sin función"}
            ).status_code
            == 404
        )

        iniciar(supervisor, agencia="002")
        assert client.get(ruta).json()["total"] == 0
        assert client.post(f"{ruta}/{primera}/aprobar", json={}).status_code == 404
        iniciar(supervisor)
        pendientes = client.get(ruta).json()["items"]
        assert {f["idObjetivo"] for f in pendientes} == {"321", "322"}
        assert all(f["puedeAprobar"] and f["puedeRechazar"] for f in pendientes)
        aceptada = client.post(f"{ruta}/{primera}/aprobar", json={})
        assert (aceptada.status_code, aceptada.json()) == (
            200,
            {"idSolicitud": primera, "estado": "Ejecutada"},
        )
        rechazada = client.post(
            f"{ruta}/{segunda}/rechazar", json={"comentario": "Rechazo ficticio"}
        )
        assert (rechazada.status_code, rechazada.json()) == (
            200,
            {"idSolicitud": segunda, "estado": "Rechazada"},
        )
        assert client.get(ruta).json()["total"] == 0
        resueltas = client.get(ruta, params={"bandeja": "resueltas"}).json()["items"]
        assert {(f["idObjetivo"], f["estado"]) for f in resueltas} == {
            ("321", "Ejecutada"),
            ("322", "Rechazada"),
        }

        # La caída de una base deja trabajo durable y el reintento aplica el rechazo una sola vez.
        with coop.begin() as conn:
            aprobacion.programar(conn, 323, titular, "001")
        with monkeypatch.context() as falla:

            def cola_indisponible(*_):
                raise problema(503, "LAB_COLA_INDISPONIBLE", "Fallo simulado.")

            falla.setattr(cola, "solicitar", cola_indisponible)
            assert (
                aprobacion.publicar_al_solicitar(cola, 323, ContextoAuditoria()) is None
            )
        assert aprobacion.reconciliar(cola, org) == (1, 1, 0)
        tercera = recuperar(cola, 323, org)
        with monkeypatch.context() as falla:

            def indisponible(*_):
                raise problema(503, "LAB_INDISPONIBLE", "Fallo simulado.")

            falla.setattr(service, "descartar_solicitud_en_cola", indisponible)
            pendiente = client.post(
                f"{ruta}/{tercera}/rechazar", json={"comentario": "Rechazo recuperable"}
            )
            assert pendiente.json()["code"] == "RECHAZO_PENDIENTE_RECUPERACION"
        assert aprobacion.reconciliar(cola, org) == (1, 1, 0)
        assert aprobacion.reconciliar(cola, org) == (0, 0, 0)

    with coop.connect() as conn:
        assert conn.execute(
            text(
                "SELECT IdTarjeta, Estado, PinAsignado FROM Tarjeta.Tarjeta ORDER BY IdTarjeta"
            )
        ).all() == [
            (321, "Generada", True),
            (322, "Anulada", False),
            (323, "Anulada", False),
        ]
        assert conn.execute(
            text(
                "SELECT IdTarjeta, RealizadoPor, Descripcion FROM Tarjeta.TarjetaHis WHERE TipoEvento='Anulacion' ORDER BY IdTarjeta"
            )
        ).all() == [
            (322, 12, "Rechazo ficticio"),
            (323, 12, "Rechazo recuperable"),
        ]
        assert (
            conn.execute(
                text(
                    "SELECT COUNT(*) FROM Seguridad.AprobacionAplicada WHERE CodigoTransaccion='TAR-SOLICITAR'"
                )
            ).scalar_one()
            == 1
        )
    assert sobres == [(321, "Aprobacion")]
    assert memoria.pines[321]["requiere_cambio"] and 322 not in memoria.pines

    for motor, carpeta in ((coop, "cooperativa"), (seg, "seguridad")):
        sql = (
            _MIGRACIONES / carpeta / "202611261600_tarjetas_aprobaciones.down.sql"
        ).read_text(encoding="utf-8")
        with pytest.raises(DBAPIError, match="57721"), motor.begin() as conn:
            conn.exec_driver_sql(
                "DECLARE @base sysname=DB_NAME(); EXEC sys.sp_set_session_context N'migration_database', @base;"
            )
            conn.exec_driver_sql(sql)
