"""Interruptor temporal AUTH_APIS_ACTIVA=false: APIs sin sesión, login intacto."""

import pytest
from fastapi.testclient import TestClient

from app.core.config.settings import Settings, get_settings
from app.core.database.db import cooperativa
from app.core.security.auth import (
    USUARIO_SIN_SESION,
    id_usuario_auditoria,
    require_roles,
)
from app.main import app
from app.modules.tarjetas import router as tarjetas_router
from tests.unit.test_autorizacion import ROLES_POR_RUTA, _concreta


@pytest.fixture
def apagado(monkeypatch):
    monkeypatch.setenv("AUTH_APIS_ACTIVA", "false")
    get_settings.cache_clear()


@pytest.fixture
def client():
    app.dependency_overrides[cooperativa] = lambda: None
    app.dependency_overrides[tarjetas_router.seguridad] = lambda: None
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()


def test_por_defecto_apagado_y_autor_8(monkeypatch, tmp_path):
    # Sin .env ni variables: los valores por defecto del código
    monkeypatch.chdir(tmp_path)
    for variable in ("AUTH_APIS_ACTIVA", "ID_USUARIO_SIN_SESION"):
        monkeypatch.delenv(variable, raising=False)

    s = Settings()

    assert (s.auth_apis_activa, s.id_usuario_sin_sesion) == (False, 8)


@pytest.mark.parametrize("ruta", list(ROLES_POR_RUTA), ids=" ".join)
def test_apagado_ninguna_api_pide_sesion_ni_rol(apagado, client, ruta):
    metodo, path = ruta
    if path == "/api/v1/auth/me":
        pytest.skip("/auth/me es del login: siempre exige sesión")

    r = client.request(metodo, _concreta(path))

    assert r.status_code not in {401, 403}


def test_apagado_el_login_sigue_exigiendo_sesion(apagado, client):
    r = client.get("/api/v1/auth/me")

    assert r.status_code == 401
    assert r.json()["code"] == "NO_AUTENTICADO"


def test_apagado_el_autor_es_el_usuario_configurado(apagado, monkeypatch):
    assert id_usuario_auditoria(USUARIO_SIN_SESION) == 8

    monkeypatch.setenv("ID_USUARIO_SIN_SESION", "3")
    get_settings.cache_clear()

    assert id_usuario_auditoria(USUARIO_SIN_SESION) == 3


def test_apagado_el_usuario_generico_tiene_todos_los_roles(apagado):
    autorizar = require_roles("SUPERVISOR", "AUDITOR", "ADMIN")

    assert autorizar(USUARIO_SIN_SESION) is USUARIO_SIN_SESION


def test_encendido_vuelve_a_exigir_sesion(client):
    # El conftest deja AUTH_APIS_ACTIVA=true en todas las pruebas
    r = client.get("/api/v1/catalogos/paises")

    assert r.status_code == 401
