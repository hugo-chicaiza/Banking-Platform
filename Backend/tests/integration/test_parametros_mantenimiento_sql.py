"""E1-10 con SQL local real y actores controlados; no acredita login WorkOS."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from datetime import datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from threading import Barrier
from typing import cast
from uuid import uuid4

import pyodbc
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.database.db import cooperativa
from app.core.security import secciones
from app.main import app
from app.modules.aprobaciones import router as aprobaciones
from app.modules.aprobaciones.manejadores import registro_inicial
from app.modules.aprobaciones.registro import Objetivo
from app.modules.aprobaciones.servicio import Servicio
from app.modules.contabilidad import plantillas
from app.modules.contabilidad import service as contabilidad
from app.modules.parametros import general
from app.modules.parametros import mantenimiento as m
from app.modules.parametros import service as e112
from app.modules.seguridad.schemas import AccesosEfectivos
from tests.integration.test_aprobaciones_sql import (
    APROBADOR,
    CONTEXTO,
    CREADOR,
    HOY,
    motores,  # noqa: F401 - fixture SQL existente, sin duplicar infraestructura
)
from tests.integration.test_e112_sql_local import TABLAS, conectar
from tests.sesion import USUARIO, simular_sesion

pytestmark = pytest.mark.skipif(
    not os.getenv("E008_LOCAL_MANIFEST"), reason="Requiere bases SQL locales propias"
)


@pytest.fixture
def laboratorio(request, monkeypatch):
    engines = request.getfixturevalue("motores")
    actores = {a.sujeto: a for a in (CREADOR, APROBADOR)}
    cola = Servicio(
        engines["seguridad"],
        engines["cooperativa"],
        registro_inicial(),
        lambda sujeto, org: actores[sujeto],
    )
    actor = [CREADOR]
    monkeypatch.setattr(m, "hoy", lambda: HOY)
    monkeypatch.setattr(
        m,
        "nombres",
        lambda valores, actual: {
            None: "Sistema",
            CREADOR.sujeto: "Solicitante QA(900801)",
        },
    )
    monkeypatch.setattr(
        secciones,
        "efectivos",
        lambda usuario: AccesosEfectivos(
            version="fixture", habilitadas=["/parametros"]
        ),
    )
    simular_sesion(
        app, replace(USUARIO, roles=("ADMIN",), id_organizacion=CREADOR.organizacion)
    )
    app.dependency_overrides[aprobaciones.actual] = lambda: actor[0]
    app.dependency_overrides[aprobaciones.servicio] = lambda: cola

    def conexion():
        with engines["cooperativa"].connect() as c:
            yield c

    app.dependency_overrides[cooperativa] = conexion

    def crear(sensible=False):
        clave = "QA_E110_" + uuid4().hex[:20].upper()
        with engines["cooperativa"].begin() as c:
            c.execute(
                text(
                    "INSERT Parametros.Parametro(Clave,Modulo,Descripcion,TipoDato,ValorMinimo,ValorMaximo,EsSensible,AdmiteAgencia) VALUES(:clave,'QA_E110','Fixture propia E1-10','Entero',1,100,:sensible,1)"
                ),
                {"clave": clave, "sensible": sensible},
            )
            id_ = general.registrar(
                c, clave, "10", HOY - timedelta(days=1), actor=CREADOR.sujeto
            )
        return clave, id_

    with TestClient(app) as client:
        yield client, crear, engines, cola, actor
    app.dependency_overrides.clear()


def programar(client, clave, dias, valor="20"):
    return client.post(
        f"/api/v1/parametros/{clave}/valores",
        json={
            "valor": valor,
            "vigenciaDesde": (HOY + timedelta(days=dias)).isoformat(),
            "idAgencia": None,
        },
    )


def test_sensible_202_sin_aplicar_hasta_aprobacion_real_sql(laboratorio):
    client, crear, engines, cola, _ = laboratorio
    clave, _ = crear(True)
    r = programar(client, clave, 1)
    assert r.status_code == 202 and r.json()["requiereAprobacion"] is True
    with engines["cooperativa"].connect() as c:
        assert general.valor(c, clave, HOY + timedelta(days=2)) == 10
    assert (
        cola.aprobar(APROBADOR, r.json()["idSolicitud"], None, CONTEXTO)["estado"]
        == "Ejecutada"
    )
    with engines["cooperativa"].connect() as c:
        assert general.valor(c, clave, HOY + timedelta(days=2)) == 20


def test_e112_no_admite_encolar_una_tarifa_como_parametro_general(laboratorio):
    client, _, engines, _, _ = laboratorio
    objetivo = uuid4().hex
    respuesta = client.post(
        "/api/v1/aprobaciones",
        json={
            "codigoTransaccion": "PAR-EDITAR",
            "tipoObjetivo": "Comision",
            "idObjetivo": objetivo,
            "contenido": {
                "valor": "0.99",
                "vigenciaDesde": (HOY + timedelta(days=1)).isoformat(),
            },
        },
    )
    assert respuesta.status_code == 404, respuesta.text
    assert respuesta.json()["code"] == "OPERACION_NO_DISPONIBLE"
    with engines["seguridad"].connect() as conn:
        assert (
            conn.execute(
                text(
                    "SELECT COUNT(*) FROM Seguridad.SolicitudAprobacion WHERE IdObjetivo=:id"
                ),
                {"id": objetivo},
            ).scalar_one()
            == 0
        )


def test_e112_catalogo_aprobacion_exige_transaccion_sensible(laboratorio):
    _, _, engines, _, _ = laboratorio
    with engines["seguridad"].connect() as conn:
        base = conn.exec_driver_sql("SELECT DB_NAME()").scalar_one()
    assert base.startswith("BankingE008_seguridad_")
    migracion = (
        Path(__file__).resolve().parents[2]
        / "migrations/seguridad/202611180805_comision_aprobacion.up.sql"
    ).read_text(encoding="utf-8")
    with closing(conectar(base)) as conn:
        conn.execute("EXEC sys.sp_set_session_context N'migration_database', ?", base)
        conn.execute(migracion)
        conn.execute(
            "UPDATE Seguridad.TransaccionesInterfaz SET EsSensible=0 "
            "WHERE CodigoTransaccion='PAR-COMISION'"
        )
        try:
            with pytest.raises(pyodbc.Error, match="57286"):
                conn.execute(migracion)
            assert (
                conn.execute(
                    "SELECT EsSensible FROM Seguridad.TransaccionesInterfaz "
                    "WHERE CodigoTransaccion='PAR-COMISION'"
                ).fetchval()
                is False
            )
        finally:
            conn.execute(
                "UPDATE Seguridad.TransaccionesInterfaz SET EsSensible=1 "
                "WHERE CodigoTransaccion='PAR-COMISION'"
            )


def test_e112_aprobacion_sql_conserva_identidad_y_tarifa_historica(
    laboratorio, monkeypatch
):
    client, _, engines, cola, actor = laboratorio
    monkeypatch.setattr(aprobaciones, "actual", lambda usuario: actor[0])
    monkeypatch.setattr(aprobaciones, "servicio", lambda: cola)
    monkeypatch.setattr(e112, "hoy", lambda: HOY)
    scripts = Path(__file__).resolve().parents[2] / "scripts/sql/e112"
    with closing(conectar("CooperativaDB_ATM02_Lab")) as fuente:
        funcion = fuente.execute(
            "SELECT OBJECT_DEFINITION(OBJECT_ID('Transacciones.fn_CalcularComision'))"
        ).fetchval()
    coop = engines["cooperativa"]
    with coop.begin() as conn:
        for esquema in ("Transacciones", "Canal", "ProductosFinancieros"):
            conn.exec_driver_sql(f"CREATE SCHEMA {esquema}")
        conn.exec_driver_sql(TABLAS)
        conn.exec_driver_sql("CREATE SCHEMA Clientes")
        conn.exec_driver_sql("CREATE SCHEMA Cuentas")
        conn.exec_driver_sql("""
            SET NOCOUNT ON;
            CREATE TABLE Clientes.Cliente (IdCliente int PRIMARY KEY, TipoCliente varchar(10));
            INSERT Clientes.Cliente VALUES (1,'Natural');
            CREATE TABLE Cuentas.Cuenta (IdCuenta int PRIMARY KEY, IdCliente int, IdSubProducto int);
            INSERT Cuentas.Cuenta VALUES (1,1,1);
            CREATE TABLE Transacciones.Transaccion (
                IdCuenta int, TipoTransaccion varchar(30), IdCanal int,
                TipoOperacion varchar(10), Estado varchar(15), FechaHoraSistema datetime2
            );
        """)
        conn.exec_driver_sql("""
            ALTER TABLE ProductosFinancieros.SubProducto ADD IdProducto int NOT NULL DEFAULT 1;
        """)
        conn.exec_driver_sql("""
            SET NOCOUNT ON;
            CREATE TABLE ProductosFinancieros.ProductoComision (
                IdComision int NOT NULL REFERENCES Transacciones.Comisiones(IdComision),
                IdProducto int NOT NULL REFERENCES ProductosFinancieros.Producto(IdProducto),
                PRIMARY KEY (IdComision, IdProducto)
            );
            INSERT ProductosFinancieros.ProductoComision VALUES (1, 1);
        """)
        conn.exec_driver_sql(funcion)
        conn.exec_driver_sql("""
            SET NOCOUNT ON;
            ALTER TABLE Transacciones.Comisiones ADD TipoComision varchar(30) NOT NULL DEFAULT 'Otro',
                Descripcion varchar(250) NOT NULL DEFAULT 'Laboratorio';
            DECLARE @base sysname=DB_NAME();
            EXEC sys.sp_set_session_context N'migration_database', @base;
        """)
        conn.exec_driver_sql(
            (scripts / "001_exoneraciones.up.sql").read_text(encoding="utf-8")
        )
        aplicar_migracion = (scripts / "004_versiones_tarifa.sql").read_text(
            encoding="utf-8"
        )
        conn.exec_driver_sql(aplicar_migracion)
    ruta = "/api/v1/parametros/comisiones/1"
    fecha = (HOY + timedelta(days=2)).isoformat()
    asociacion = client.post(
        "/api/v1/parametros/comisiones",
        json={
            "idComision": 1,
            "codigoTipoTransaccion": "Retiro",
            "idCanal": 2,
            "vigenciaDesde": HOY.isoformat(),
        },
    )
    assert asociacion.status_code == 201, asociacion.text
    exoneracion = client.post(
        "/api/v1/parametros/exoneraciones",
        json={
            "idComision": 1,
            "porcentajeExonerado": 50,
            "vigenciaDesde": HOY.isoformat(),
        },
    )
    assert exoneracion.status_code == 201, exoneracion.text

    def solicitar():
        r = client.patch(ruta, json={"valor": "0.99", "vigenciaDesde": fecha})
        assert r.status_code == 202, r.text
        return r.json()["idSolicitud"]

    def cobrador(dia):
        with coop.connect() as conn:
            return conn.execute(
                text("""
                SELECT MontoComision FROM Transacciones.fn_CalcularComision('Retiro',2,100,:fecha)
            """),
                {"fecha": dia},
            ).scalar_one()

    mismo_dia = client.patch(ruta, json={"valor": "0.99", "vigenciaDesde": str(HOY)})
    assert (
        mismo_dia.status_code == 422 and "VIGENCIA_TARIFA_NO_FUTURA" in mismo_dia.text
    )

    for dia_aprobacion in (HOY + timedelta(days=2), HOY + timedelta(days=3)):
        vencida = solicitar()
        with monkeypatch.context() as reloj:
            reloj.setattr(e112, "hoy", lambda dia=dia_aprobacion: dia)
            with pytest.raises(HTTPException) as error:
                cola.aprobar(APROBADOR, vencida, None, CONTEXTO)
        assert error.value.status_code == 409
        detalle = cast(object, error.value.detail)
        assert (
            isinstance(detalle, dict)
            and detalle.get("code") == "VIGENCIA_TARIFA_VENCIDA"
        )
        assert cobrador(fecha) == Decimal("0.45")

    primera = solicitar()
    assert cobrador(fecha) == Decimal("0.45")
    assert (
        client.patch(ruta, json={"valor": "0.99", "vigenciaDesde": fecha}).status_code
        == 409
    )
    auto = replace(CREADOR, permisos=APROBADOR.permisos)
    with pytest.raises(HTTPException) as error:
        cola.aprobar(auto, primera, None, CONTEXTO)
    assert error.value.status_code == 403
    with pytest.raises(HTTPException) as error:
        cola.aprobar(replace(APROBADOR, permisos=frozenset()), primera, None, CONTEXTO)
    assert error.value.status_code == 403
    assert (
        cola.resolver(APROBADOR, primera, "Rechazada", "Prueba", CONTEXTO)["estado"]
        == "Rechazada"
    )
    assert cobrador(fecha) == Decimal("0.45")

    desactualizada = solicitar()
    assert (
        client.patch(
            ruta, json={"descripcion": "Editada entre solicitud y aprobación"}
        ).status_code
        == 200
    )
    with pytest.raises(HTTPException) as error:
        cola.aprobar(APROBADOR, desactualizada, None, CONTEXTO)
    detalle = cast(object, error.value.detail)
    assert (
        isinstance(detalle, dict) and detalle.get("code") == "SOLICITUD_DESACTUALIZADA"
    )
    with engines["seguridad"].connect() as conn:
        assert (
            conn.execute(
                text("""
            SELECT Estado FROM Seguridad.SolicitudAprobacion WHERE IdSolicitud=:id
        """),
                {"id": desactualizada},
            ).scalar_one()
            == "Fallida"
        )
    assert cobrador(fecha) == Decimal("0.45")

    aprobada = solicitar()
    barrera = Barrier(2)

    def aprobar_en_paralelo(persona):
        barrera.wait(timeout=10)
        try:
            assert (
                cola.aprobar(persona, aprobada, None, CONTEXTO)["estado"] == "Ejecutada"
            )
            return 200
        except HTTPException as error:
            return error.status_code

    otro = replace(APROBADOR, sujeto="user_checker_e112", id_interno=900803)
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(aprobar_en_paralelo, (APROBADOR, otro))) == [200, 409]
    with pytest.raises(HTTPException) as error:
        cola.aprobar(APROBADOR, aprobada, None, CONTEXTO)
    assert error.value.status_code == 409

    assert cobrador(HOY) == Decimal("0.45")
    assert cobrador(fecha) == Decimal("0.99")
    with coop.begin() as conn:
        cobro = e112.comision(
            conn,
            "Retiro",
            2,
            1,
            datetime.combine(HOY + timedelta(days=2), time(10)),
            monto_operacion=Decimal(100),
        )[0]
        assert cobro.id_comision == 1 and cobro.monto_base == cobrador(fecha)
        assert cobro.monto_cobrar == Decimal("0.50")
        assert cobro.id_exoneracion == exoneracion.json()["idExoneracion"]
    assert Decimal(
        str(
            client.get(ruta + "/tarifa", params={"fecha": HOY.isoformat()}).json()[
                "valor"
            ]
        )
    ) == Decimal("0.45")
    assert Decimal(
        str(client.get(ruta + "/tarifa", params={"fecha": fecha}).json()["valor"])
    ) == Decimal("0.99")
    assert (
        client.patch(ruta, json={"vigenciaDesde": fecha, "valor": "0.75"}).status_code
        == 409
    )
    with coop.begin() as conn:
        conn.exec_driver_sql("""
            DECLARE @base sysname=DB_NAME();
            EXEC sys.sp_set_session_context N'migration_database', @base;
        """)
        conn.exec_driver_sql(aplicar_migracion)
        assert (
            conn.exec_driver_sql("""
            SELECT COUNT(*) FROM Transacciones.ComisionValor WHERE IdComision=1
        """).scalar_one()
            == 2
        )
        assert (
            conn.execute(
                text("""
            SELECT COUNT(*) FROM Transacciones.ComisionValor WHERE IdSolicitud=:id
        """),
                {"id": aprobada},
            ).scalar_one()
            == 1
        )
        assert conn.exec_driver_sql("""
            SELECT IdComision FROM Transacciones.ComisionTipoTransaccion
        """).scalars().all() == [1]
        assert conn.exec_driver_sql("""
            SELECT IdComision FROM Transacciones.ExoneracionComision
        """).scalars().all() == [1]
        assert conn.exec_driver_sql("""
            SELECT IdComision, IdProducto FROM ProductosFinancieros.ProductoComision
        """).all() == [(1, 1)]
    with engines["seguridad"].connect() as conn:
        fila = conn.execute(
            text("""
            SELECT Antes, Despues, SolicitadoPor, ResueltoPor
            FROM Seguridad.SolicitudAprobacion WHERE IdSolicitud=:id
        """),
            {"id": aprobada},
        ).one()
        assert Decimal(json.loads(fila.Antes)["valor"]) == Decimal("0.45")
        assert Decimal(json.loads(fila.Despues)["valor"]) == Decimal("0.99")
        assert fila.SolicitadoPor == CREADOR.sujeto
        assert fila.ResueltoPor in {APROBADOR.sujeto, otro.sujeto}

    desactivar = client.patch(ruta, json={"estado": "I"})
    assert desactivar.status_code == 200, desactivar.text
    assert desactivar.json()["estado"] == "I"
    with coop.connect() as conn:
        assert (
            conn.exec_driver_sql(
                "SELECT COUNT(*) FROM Transacciones.ComisionValor WHERE IdComision = 1"
            ).scalar_one()
            == 2
        )


def test_historico_422_y_valor_vigente_no_cancelable(laboratorio):
    client, crear, _, _, _ = laboratorio
    clave, id_ = crear()
    r = client.patch(f"/api/v1/parametros/{clave}/valores/{id_}", json={"valor": "50"})
    assert r.status_code == 422 and r.json()["code"] == "VIGENCIA_PASADA"
    r = client.delete(f"/api/v1/parametros/{clave}/valores/{id_}")
    assert r.status_code == 409 and r.json()["code"] == "VALOR_YA_VIGENTE"


def test_cancelar_cadena_futura_restituye_anterior_sin_solapar(laboratorio):
    client, crear, engines, _, _ = laboratorio
    clave, id_inicial = crear()
    primero = programar(client, clave, 2)
    segundo = programar(client, clave, 4, "30")
    assert primero.status_code == segundo.status_code == 201
    r = client.delete(
        f"/api/v1/parametros/{clave}/valores/{primero.json()['idParametroValor']}"
    )
    assert r.status_code == 204
    with engines["cooperativa"].connect() as c:
        assert general.valor(c, clave, HOY + timedelta(days=3)) == 10
        assert general.valor(c, clave, HOY + timedelta(days=4)) == 30
    assert (
        client.delete(
            f"/api/v1/parametros/{clave}/valores/{segundo.json()['idParametroValor']}"
        ).status_code
        == 204
    )
    with engines["cooperativa"].connect() as c:
        assert general.valor(c, clave, HOY + timedelta(days=10)) == 10
        assert (
            c.execute(
                text(
                    "SELECT VigenciaHasta FROM Parametros.ParametroValor WHERE IdParametroValor=:id"
                ),
                {"id": id_inicial},
            ).scalar_one()
            is None
        )


def test_detalle_lista_actual_programado_historial_y_auditoria(laboratorio):
    client, crear, engines, _, _ = laboratorio
    clave, _ = crear()
    assert programar(client, clave, 2).status_code == 201
    r = client.get(f"/api/v1/parametros/{clave}")
    assert r.status_code == 200
    p = r.json()
    assert p["valorActual"]["valor"] == "10" and p["proximoValor"]["valor"] == "20"
    assert len(p["historial"]) == 2 and p["puedeEditar"] is True
    assert (
        client.get("/api/v1/parametros", params={"buscar": clave}).json()["total"] == 1
    )
    with engines["cooperativa"].connect() as c:
        assert (
            c.execute(
                text(
                    "SELECT COUNT(*) FROM Auditoria.EventoPendiente WHERE CodigoEvento='PAR_VALOR_REGISTRADO' AND JSON_VALUE(Contenido,'$.idObjetivo')=:clave"
                ),
                {"clave": clave},
            ).scalar_one()
            == 1
        )


def test_permiso_actual_y_rango_se_validan_antes_de_escribir(laboratorio):
    client, crear, _, _, actor = laboratorio
    clave, _ = crear()
    r = programar(client, clave, 1, "101")
    assert r.status_code == 422 and r.json()["code"] == "VALOR_FUERA_DE_RANGO"
    actor[0] = APROBADOR
    r = programar(client, clave, 1)
    assert r.status_code == 403 and r.json()["code"] == "SIN_PERMISO"


def test_rutas_e112_no_son_capturadas_por_la_clave_dinamica():
    rutas = list(app.openapi()["paths"])
    assert rutas.index("/api/v1/parametros/comisiones") < rutas.index(
        "/api/v1/parametros/{clave}"
    )
    assert secciones.seccion_api("GET", "/api/v1/parametros/comisiones") == ""
    assert (
        secciones.seccion_api("GET", "/api/v1/parametros/SESION_TIEMPO")
        == "parametros.consultar"
    )


def test_relevo_reutilizado_respeta_tipo_parametro_y_filtro_propio(laboratorio):
    from app.modules.aprobaciones.relevo import entregar

    client, crear, engines, _, _ = laboratorio
    clave, _ = crear()
    assert programar(client, clave, 1).status_code == 201
    with engines["cooperativa"].connect() as c:
        evento = c.execute(
            text(
                "SELECT IdEvento FROM Auditoria.EventoPendiente WHERE JSON_VALUE(Contenido,'$.idObjetivo')=:clave"
            ),
            {"clave": clave},
        ).scalar_one()
    assert (
        entregar(engines["cooperativa"], engines["seguridad"], ids_evento=[str(evento)])
        == 1
    )
    assert (
        entregar(engines["cooperativa"], engines["seguridad"], ids_evento=[str(evento)])
        == 0
    )
    with engines["seguridad"].connect() as c:
        tabla = c.execute(
            text(
                "SELECT a.TablaAfectada FROM Auditoria.EventoDetalle e JOIN Auditoria.Auditoria a ON a.AuditoriaID=e.AuditoriaID WHERE e.IdEvento=:id"
            ),
            {"id": str(evento)},
        ).scalar_one()
        assert tabla == "Parametros.Parametro"


def test_fallo_auditoria_revierte_valor_y_frontera_anterior(laboratorio, monkeypatch):
    client, crear, engines, _, _ = laboratorio
    clave, _ = crear()

    def fallo(*args):
        raise SQLAlchemyError("Fallo de outbox controlado en SQL local propio")

    monkeypatch.setattr(m, "auditar", fallo)
    assert programar(client, clave, 1).status_code == 500
    with engines["cooperativa"].connect() as c:
        valores = general.historial(c, clave)
        assert len(valores) == 1 and valores[0]["VigenciaHasta"] is None


def test_plantilla_resuelve_en_cola_con_segunda_identidad(laboratorio, monkeypatch):
    _, _, engines, _, _ = laboratorio
    creador = replace(
        CREADOR, roles=("CONTADOR",), permisos=frozenset({"con-plantilla-editar"})
    )
    aprobador = replace(APROBADOR, permisos=frozenset({"con-plantilla-aprobar"}))
    actores = {a.sujeto: a for a in (creador, aprobador)}
    cola = Servicio(
        engines["seguridad"],
        engines["cooperativa"],
        registro_inicial(),
        lambda sujeto, org: actores[sujeto],
    )
    monkeypatch.setattr(
        contabilidad, "obtener_fecha_contable_actual", lambda conn: {"fecha": HOY}
    )
    monkeypatch.setattr(plantillas, "validar_lineas", lambda conn, lineas: [])
    with engines["seguridad"].begin() as conn:
        conn.exec_driver_sql("""
            IF OBJECT_ID('Auditoria.TipoEvento','U') IS NULL
                CREATE TABLE Auditoria.TipoEvento (
                    CodigoEvento varchar(40) PRIMARY KEY, Modulo varchar(50),
                    Severidad varchar(20), EnTransaccion bit, Estado char(1) DEFAULT 'A'
                );
            DECLARE @base sysname = DB_NAME();
            EXEC sys.sp_set_session_context N'migration_database', @base;
        """)
        script = (
            Path(__file__).resolve().parents[2]
            / "migrations/seguridad/202611191500_plantillas_aprobacion.up.sql"
        ).read_text(encoding="utf8")
        conn.exec_driver_sql(script)
        conn.exec_driver_sql(script)
    with engines["cooperativa"].begin() as conn:
        conn.exec_driver_sql("""
            CREATE SCHEMA Contabilidad;
        """)
        conn.exec_driver_sql("""
            CREATE TABLE Contabilidad.PlantillaAsiento (
                IdPlantillaAsiento int PRIMARY KEY, CodigoPlantilla varchar(30),
                CreadoPor int, Estado bit, VigenciaDesde date, VigenciaHasta date NULL,
                AprobadoPor int NULL, FechaAprobacion datetime2 NULL
            );
        """)
        for id_, activo, desde in (
            (1, 1, HOY),
            (2, 0, HOY + timedelta(days=1)),
            (3, 0, HOY + timedelta(days=2)),
        ):
            conn.exec_driver_sql(
                """
                INSERT Contabilidad.PlantillaAsiento
                    (IdPlantillaAsiento,CodigoPlantilla,CreadoPor,Estado,VigenciaDesde)
                VALUES (?,'QA',?,?,?)
            """,
                (id_, creador.id_interno, activo, desde),
            )
    monkeypatch.setattr(
        plantillas.repository, "obtener_lineas_plantilla", lambda conn, id_: []
    )

    def solicitar(id_):
        return cola.solicitar(
            creador,
            "CON-PLANTILLA",
            Objetivo("PlantillaAsiento", str(id_), None),
            {"creador": creador.id_interno},
            HOY,
            CONTEXTO,
        )

    rechazada = solicitar(3)
    assert (
        cola.resolver(aprobador, rechazada, "Rechazada", "QA", CONTEXTO)["estado"]
        == "Rechazada"
    )
    with pytest.raises(HTTPException) as repetida:
        solicitar(3)
    assert repetida.value.status_code == 409
    aprobada = solicitar(2)
    with pytest.raises(HTTPException) as propia:
        cola.aprobar(creador, aprobada, None, CONTEXTO)
    assert propia.value.status_code == 403
    assert cola.aprobar(aprobador, aprobada, None, CONTEXTO)["estado"] == "Ejecutada"
    with pytest.raises(HTTPException) as repetida:
        cola.aprobar(aprobador, aprobada, None, CONTEXTO)
    assert repetida.value.status_code == 409
    with engines["cooperativa"].connect() as conn:
        filas = conn.exec_driver_sql("""
            SELECT Estado,VigenciaHasta,AprobadoPor FROM Contabilidad.PlantillaAsiento
            ORDER BY IdPlantillaAsiento
        """).all()
        assert filas == [
            (True, HOY, None),
            (True, None, aprobador.id_interno),
            (False, None, None),
        ]


def test_importacion_respeta_limite_vigente_y_semilla_repetible(laboratorio):
    from app.modules.contabilidad import importaciones

    _, _, engines, _, _ = laboratorio
    script = (
        Path(__file__).resolve().parents[2]
        / "migrations/cooperativa/202611191500_importacion_limite_filas.up.sql"
    ).read_text(encoding="utf8")
    with engines["cooperativa"].begin() as conn:
        conn.exec_driver_sql("""
            DECLARE @base sysname = DB_NAME();
            EXEC sys.sp_set_session_context N'migration_database', @base;
        """)
        conn.exec_driver_sql(script)
        assert importaciones._limite_filas(conn) == 5000
        conn.exec_driver_sql("""
            UPDATE v SET Valor='1' FROM Parametros.ParametroValor v
            JOIN Parametros.Parametro p ON p.IdParametro=v.IdParametro
            WHERE p.Clave='CON_IMPORTACION_MAX_FILAS'
        """)
        conn.exec_driver_sql(script)
        assert importaciones._limite_filas(conn) == 1
    with (
        engines["cooperativa"].connect() as conn,
        pytest.raises(HTTPException) as error,
    ):
        importaciones.guardar_revision(conn, CREADOR.id_interno, "qa.csv", [{}, {}])
    assert error.value.status_code == 422
