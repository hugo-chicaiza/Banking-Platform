"""Rutas reales y dos bases SQL reales locales; solo la identidad se controla aqui."""

import os
from dataclasses import replace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.aprobaciones import router as rutas
from tests.integration.test_aprobaciones_sql import APROBADOR, CREADOR, caso, motores  # noqa: F401
from tests.sesion import USUARIO, simular_sesion

pytestmark = pytest.mark.skipif(
    not os.environ.get("E008_LOCAL_MANIFEST"),
    reason="Requiere laboratorio SQL local E0-08",
)


@pytest.fixture
def http(request):
    servicio, id_, _, _ = request.getfixturevalue("caso")
    app = FastAPI()
    app.include_router(rutas.router, prefix="/api/v1")
    actor = [CREADOR]
    app.dependency_overrides[rutas.actual] = lambda: actor[0]
    app.dependency_overrides[rutas.servicio] = lambda: servicio

    def sesion():
        a = actor[0]
        simular_sesion(
            app,
            replace(
                USUARIO,
                id_usuario=a.sujeto,
                id_organizacion=a.organizacion,
                id_interno=a.id_interno,
                id_agencia=None if a.global_admin else "001",
                roles=a.roles,
                permisos=tuple(a.permisos),
            ),
        )

    sesion()
    with TestClient(app) as cliente:
        yield cliente, actor, sesion, id_


def test_bandejas_detalle_y_permiso_de_acciones(http):
    client, actor, sesion, id_ = http
    propia = client.get(f"/api/v1/aprobaciones/{id_}")
    assert propia.status_code == 200, propia.text
    assert (
        propia.json()["puedeAprobar"] is False
        and propia.json()["puedeCancelar"] is True
    )
    assert client.get("/api/v1/aprobaciones?bandeja=mias").status_code == 200
    actor[0] = APROBADOR
    sesion()
    consulta = client.get("/api/v1/aprobaciones/accesos")
    assert consulta.status_code == 200, consulta.text
    assert consulta.json()["puedeVer"] is True
    assert client.get(f"/api/v1/aprobaciones/{id_}").json()["puedeAprobar"] is True
    respuesta = client.post(f"/api/v1/aprobaciones/{id_}/aprobar", json={})
    assert respuesta.status_code == 200 and respuesta.json()["estado"] == "Ejecutada", (
        respuesta.text
    )
    detalle = client.get(f"/api/v1/aprobaciones/{id_}").json()
    assert detalle["puedeAprobar"] is False
    assert [e["estadoNuevo"] for e in detalle["eventos"]] == [
        "Pendiente",
        "Aprobada",
        "Ejecutada",
    ]


def test_self_403_y_error_visible_no_500(http):
    client, _, _, id_ = http
    r = client.post(f"/api/v1/aprobaciones/{id_}/aprobar", json={})
    assert r.status_code == 403 and r.json()["code"] == "APROBADOR_ES_SOLICITANTE"
    assert r.json()["traceId"]
    assert "Traceback" not in r.text


def test_contrato_no_acepta_actor_ni_agencia_000(http):
    client, _, _, _ = http
    body = {
        "codigoTransaccion": "PAR-EDITAR",
        "tipoObjetivo": "Parametro",
        "idObjetivo": "CLAVE_QA",
        "idAgencia": "000",
        "contenido": {},
        "actor": "otra_persona",
    }
    r = client.post("/api/v1/aprobaciones", json=body)
    assert r.status_code == 400 and r.json()["code"] == "DATOS_INVALIDOS"


def test_router_exige_sesion_sin_ejecutar_sql():
    app = FastAPI()
    app.include_router(rutas.router, prefix="/api/v1")
    with TestClient(app) as client:
        r = client.get("/api/v1/aprobaciones")
    assert r.status_code == 401
