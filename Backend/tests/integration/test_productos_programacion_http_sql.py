"""HTTP y persistencia SQL local reales con identidad controlada, sin login WorkOS."""

import os
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.core.database.db import cooperativa
from app.main import app
from app.modules.aprobaciones import router as apr
from app.modules.productos import programacion_api
from app.modules.seguridad import funciones
from tests.integration import test_productos_programacion_sql as base_sql
from tests.sesion import USUARIO, simular_sesion

motores = base_sql.motores
caso = base_sql.caso
pytestmark = pytest.mark.skipif(
    not os.getenv("E303_LOCAL_MANIFEST"), reason="Requiere SQL local E3-03 propio"
)


@pytest.fixture(params=[False, True], ids=["WorkOS", "Funciones-y-WorkOS"])
def http_sql(motores, caso, monkeypatch, request):
    actor = [base_sql.MAKER]
    monkeypatch.setattr(programacion_api, "motor", lambda base: motores[base])
    monkeypatch.setattr(funciones, "activa", lambda: request.param)
    monkeypatch.setattr(funciones, "get_engine", lambda base: motores[base])

    def conexion():
        with motores["cooperativa"].connect() as c:
            yield c

    app.dependency_overrides[cooperativa] = conexion
    app.dependency_overrides[apr.actual] = lambda: actor[0]
    app.dependency_overrides[apr.servicio] = lambda: caso[0]

    def sesion(nuevo):
        actor[0] = nuevo
        simular_sesion(
            app,
            replace(
                USUARIO,
                roles=nuevo.roles,
                permisos=tuple(nuevo.permisos | {"prd-consultar"}),
                id_organizacion=base_sql.ORG,
                id_interno=nuevo.id_interno,
            ),
        )

    sesion(base_sql.MAKER)
    with TestClient(app, raise_server_exceptions=False) as cliente:
        yield cliente, caso, sesion
    app.dependency_overrides.clear()


def test_ac2_http_vigente_no_editable_y_sin_escritura(http_sql):
    client, caso, _ = http_sql
    base = f"/api/v1/productos/subproductos/{caso[1].id}"
    r = client.patch(
        base + f"/condiciones/{caso[2]}", json={"montoAperturaMinimo": "999"}
    )
    assert r.status_code == 409 and r.json()["code"] == "CONJUNTO_NO_EDITABLE"
    datos = client.get(base + "/vigencias")
    assert datos.status_code == 200
    assert len(datos.json()["condiciones"]) == 1
    assert str(datos.json()["condiciones"][0]["montoAperturaMinimo"]) in (
        "25.00",
        "25",
        "25.0",
    )


def test_202_http_aprobacion_y_cancelacion_conservan_vigente(http_sql):
    client, caso, sesion = http_sql
    base = f"/api/v1/productos/subproductos/{caso[1].id}"
    cuerpo = base_sql.condicion()["datos"]
    r = client.post(base + "/condiciones", json=cuerpo)
    assert r.status_code == 202 and r.json()["requiereAprobacion"] is True
    id_ = r.json()["idSolicitud"]
    assert len(client.get(base + "/vigencias").json()["condiciones"]) == 1
    propia = client.post(
        f"/api/v1/aprobaciones/{id_}/aprobar", json={"comentario": "Intento propio QA"}
    )
    assert (
        propia.status_code == 403
        and propia.json()["code"] == "APROBADOR_ES_SOLICITANTE"
    )
    sesion(base_sql.CHECKER)
    aprobada = client.post(
        f"/api/v1/aprobaciones/{id_}/aprobar",
        json={"comentario": "Aprobacion SQL local QA"},
    )
    assert aprobada.status_code == 200 and aprobada.json()["estado"] == "Ejecutada"
    valores = client.get(base + "/vigencias").json()["condiciones"]
    assert len(valores) == 2
    futuro = valores[-1]["idCondicion"]
    sesion(base_sql.MAKER)
    r = client.delete(base + f"/condiciones/{futuro}")
    assert r.status_code == 202
    sesion(base_sql.CHECKER)
    r = client.post(
        f"/api/v1/aprobaciones/{r.json()['idSolicitud']}/aprobar",
        json={"comentario": "Cancelar futuro QA"},
    )
    assert r.status_code == 200 and r.json()["estado"] == "Ejecutada"
    valores = client.get(base + "/vigencias").json()["condiciones"]
    assert valores[0]["vigenciaHasta"] is None and valores[-1]["estado"] == "Cancelada"


def test_permiso_backend_no_se_sustituye_por_rol_o_payload(http_sql):
    client, caso, sesion = http_sql
    from dataclasses import replace

    sesion(replace(base_sql.MAKER, permisos=frozenset()))
    r = client.post(
        f"/api/v1/productos/subproductos/{caso[1].id}/condiciones",
        json={**base_sql.condicion()["datos"], "aprobado": True},
    )
    assert r.status_code == 403
    sesion(base_sql.CHECKER)
    r = client.post(
        f"/api/v1/productos/subproductos/{caso[1].id}/condiciones",
        json=base_sql.condicion()["datos"],
    )
    assert r.status_code == 403
