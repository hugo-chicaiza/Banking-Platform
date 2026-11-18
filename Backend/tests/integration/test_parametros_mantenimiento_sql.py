"""E1-10 con SQL local real y actores controlados; no acredita login WorkOS."""

import os
from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.database.db import cooperativa
from app.core.security import secciones
from app.main import app
from app.modules.aprobaciones import router as aprobaciones
from app.modules.aprobaciones.manejadores import registro_inicial
from app.modules.aprobaciones.servicio import Servicio
from app.modules.parametros import general
from app.modules.parametros import mantenimiento as m
from app.modules.seguridad.schemas import AccesosEfectivos
from tests.integration.test_aprobaciones_sql import (
    APROBADOR,
    CONTEXTO,
    CREADOR,
    HOY,
    motores,  # noqa: F401 - fixture SQL existente, sin duplicar infraestructura
)
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
