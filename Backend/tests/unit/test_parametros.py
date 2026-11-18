from dataclasses import replace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.api.errors import problema
from app.core.database.db import cooperativa
from app.core.security.auth import id_usuario_auditoria
from app.modules.parametros.router import router
from tests.sesion import USUARIO, simular_sesion, usuario_con_roles

BASE = "/api/v1/parametros"
RUTAS = [
    ("GET", "/comisiones"),
    ("POST", "/comisiones"),
    ("PATCH", "/comisiones/1"),
    ("GET", "/exoneraciones"),
    ("POST", "/exoneraciones"),
    ("PATCH", "/exoneraciones/1"),
]


@pytest.fixture
def api():
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    # Los tests de acceso y validación no deben llegar al repositorio.
    app.dependency_overrides[cooperativa] = lambda: None
    return app


@pytest.mark.parametrize("metodo,ruta", RUTAS)
def test_sesion_obligatoria(api, metodo, ruta):
    r = TestClient(api).request(metodo, BASE + ruta)
    assert r.status_code == 401


@pytest.mark.parametrize("metodo,ruta", [(m, r) for m, r in RUTAS if m != "GET"])
def test_otro_rol_no_escribe(api, metodo, ruta):
    simular_sesion(api, usuario_con_roles("SUPERVISOR", "ASESOR", "CONTADOR"))
    r = TestClient(api).request(metodo, BASE + ruta, json={})
    assert r.status_code == 403
    assert r.json()["code"] == "SIN_PERMISO"


def test_permiso_no_sustituye_vinculo_de_actor(api):
    simular_sesion(api, replace(USUARIO, id_interno=None))
    api.dependency_overrides.pop(id_usuario_auditoria)
    r = TestClient(api).post(BASE + "/comisiones", json={})
    assert r.status_code == 403
    assert r.json()["code"] == "USUARIO_NO_REGISTRADO"


@pytest.mark.parametrize(
    "campo,valor",
    [
        ("registradoPor", 1),
        ("creadoPor", 1),
        ("idSolicitud", 2),
        ("porcentajeExonerado", -0.01),
        ("porcentajeExonerado", 100.01),
        ("operacionesGratisMes", -1),
        ("operacionesGratisMes", True),
        ("porcentajeExonerado", "NaN"),
    ],
)
def test_exoneracion_rechaza_actor_y_valores_invalidos(api, campo, valor):
    simular_sesion(api)
    r = TestClient(api).post(
        BASE + "/exoneraciones",
        json={
            "idComision": 1,
            "porcentajeExonerado": 50,
            "vigenciaDesde": "2099-01-01",
            campo: valor,
        },
    )
    assert r.status_code == 400


@pytest.mark.parametrize("ruta", ["/comisiones/1", "/exoneraciones/1"])
@pytest.mark.parametrize("cuerpo", [{}, {"estado": None}, {"registradoPor": 1}])
def test_patch_invalido(api, ruta, cuerpo):
    simular_sesion(api)
    assert TestClient(api).patch(BASE + ruta, json=cuerpo).status_code == 400


def test_contrato_openapi_sin_actor_en_entradas(api):
    contrato = api.openapi()
    assert len(contrato["paths"]) == 4
    for nombre in (
        "ComisionCreate",
        "AsociarComision",
        "ComisionUpdate",
        "ExoneracionCreate",
        "ExoneracionUpdate",
    ):
        props = contrato["components"]["schemas"][nombre]["properties"]
        assert not {"registradoPor", "creadoPor", "idSolicitud"} & props.keys()
    assert (
        "404"
        in contrato["paths"][BASE + "/comisiones/{idComision}"]["patch"]["responses"]
    )


def test_escritura_solo_admin(api, monkeypatch):
    from app.modules.parametros import service

    def permitido(*args):
        raise problema(422, "LLEGO_AL_SERVICIO", "Acceso verificado.")

    monkeypatch.setattr(service, "crear_exoneracion", permitido)
    cuerpo = {
        "idComision": 1,
        "porcentajeExonerado": 100,
        "vigenciaDesde": "2099-01-01",
    }
    # Ningún permiso de WorkOS sustituye al rol ADMIN en esta escritura
    simular_sesion(api, replace(usuario_con_roles("ASESOR"), permisos=("prd-editar",)))
    r = TestClient(api).post(BASE + "/exoneraciones", json=cuerpo)
    assert r.status_code == 403
    simular_sesion(api, usuario_con_roles("ADMIN"))
    r = TestClient(api).post(BASE + "/exoneraciones", json=cuerpo)
    assert r.status_code == 422 and r.json()["code"] == "LLEGO_AL_SERVICIO"


def test_catalogo_legado_no_puede_cambiar_valor(monkeypatch, eventos_auditados):
    from unittest.mock import Mock

    from fastapi import HTTPException

    from app.modules.catalogos import administracion

    conn = Mock()
    monkeypatch.setattr(administracion, "_fila", lambda *args: {"id": "1", "valor": 1})
    with pytest.raises(HTTPException) as error:
        administracion.actualizar(
            conn, "comisiones", "1", {"valor": 2}, USUARIO, "127.0.0.1"
        )
    assert error.value.status_code == 404
    conn.execute.assert_not_called()
    conn.rollback.assert_called_once()
    assert eventos_auditados[-1].resultado == "Fallido"
