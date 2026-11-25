"""Autorización por sección y guardado SQL atómico, sin WorkOS ni SQL reales."""

import re
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from app.core.database.db import cooperativa, seguridad
from app.core.security import audit, secciones
from app.core.security.auth import ROLES
from app.main import app
from app.modules.clientes import service as clientes
from app.modules.clientes.schemas import PageCliente
from app.modules.seguridad import accesos, repository
from tests.sesion import simular_sesion, usuario_con_roles


class BaseLocal:
    def __init__(self):
        self.filas = {}
        self.eventos = []
        self.lock = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    @contextmanager
    def begin(self):
        anteriores, eventos = dict(self.filas), list(self.eventos)
        try:
            yield self
        except BaseException:
            self.filas, self.eventos = anteriores, eventos
            raise

    def execute(self, sentencia):
        assert "sp_getapplock" in str(sentencia)
        return SimpleNamespace(scalar_one=lambda: self.lock)


@pytest.fixture
def entorno(monkeypatch):
    base = BaseLocal()
    monkeypatch.setattr(repository, "pestanas", lambda conn: sorted(base.filas.items()))
    monkeypatch.setattr(
        repository,
        "reemplazar_pestanas",
        lambda conn, filas, usuario: setattr(base, "filas", dict(filas)),
    )
    monkeypatch.setattr(
        audit, "_insertar", lambda conn, evento: base.eventos.append(evento)
    )
    monkeypatch.setattr(
        accesos, "get_engine", lambda nombre: SimpleNamespace(connect=lambda: base)
    )
    config = SimpleNamespace(editor_accesos_activo=True)
    monkeypatch.setattr(accesos, "get_settings", lambda: config)
    monkeypatch.setattr(secciones, "get_settings", lambda: config)
    app.dependency_overrides[seguridad] = lambda: base
    simular_sesion(app, usuario_con_roles("ADMIN"))
    with TestClient(app, raise_server_exceptions=False) as cliente:
        yield cliente, base, config
    app.dependency_overrides.clear()


def cuerpo(cliente, roles=None):
    actual = cliente.get("/api/v1/seguridad/pestanas/configuracion")
    assert actual.status_code == 200, actual.text
    return {
        "version": actual.json()["version"],
        "motivo": "Ajuste de acceso del puesto",
        "pestanas": [{"pestana": "/clientes-busqueda", "roles": roles or []}],
    }


def test_guarda_y_retira_api_y_sesion_sin_cambiar_workos(entorno, monkeypatch):
    cliente, base, _ = entorno
    simular_sesion(app, usuario_con_roles("ASESOR"))
    monkeypatch.setattr(
        clientes,
        "listar_clientes",
        lambda conn, filtros: PageCliente(items=[], total=0, page=1, page_size=20),
    )
    app.dependency_overrides[cooperativa] = lambda: object()
    assert (
        cliente.post("/api/v1/clientes/busqueda", json={"estado": "Activo"}).status_code
        == 200
    )
    simular_sesion(app, usuario_con_roles("ADMIN"))
    datos = cuerpo(cliente)
    assert cliente.put("/api/v1/seguridad/pestanas", json=datos).status_code == 200
    assert base.eventos[0].descripcion.endswith("motivo=Ajuste de acceso del puesto")
    simular_sesion(app, usuario_con_roles("ASESOR"))
    assert (
        cliente.post("/api/v1/clientes/busqueda", json={"estado": "Activo"}).status_code
        == 403
    )
    assert (
        "/clientes-busqueda"
        not in cliente.get("/api/v1/auth/me").json()["accesosSecciones"]["habilitadas"]
    )
    simular_sesion(app, usuario_con_roles("ADMIN"))
    datos = cuerpo(cliente, ["ASESOR"])
    assert cliente.put("/api/v1/seguridad/pestanas", json=datos).status_code == 200
    simular_sesion(app, usuario_con_roles("ASESOR"))
    assert (
        cliente.post("/api/v1/clientes/busqueda", json={"estado": "Activo"}).status_code
        == 200
    )


def test_version_desactualizada_no_sobrescribe(entorno):
    cliente, base, _ = entorno
    datos = cuerpo(cliente)
    assert cliente.put("/api/v1/seguridad/pestanas", json=datos).status_code == 200
    assert (
        cliente.put(
            "/api/v1/seguridad/pestanas", json=datos | {"pestanas": []}
        ).status_code
        == 409
    )
    assert base.filas == {"/clientes-busqueda": ""}


def test_fallo_auditoria_revierte_configuracion(entorno, monkeypatch):
    cliente, base, _ = entorno
    monkeypatch.setattr(audit, "_insertar", Mock(side_effect=SQLAlchemyError("falso")))
    respuesta = cliente.put("/api/v1/seguridad/pestanas", json=cuerpo(cliente))
    assert respuesta.status_code == 503
    assert base.filas == {}


@pytest.mark.parametrize(
    "pestanas,codigo",
    [
        ([{"pestana": "/inventada", "roles": []}], "SECCION_DESCONOCIDA"),
        (
            [{"pestana": "/organizacion/agencias", "roles": ["ASESOR"]}],
            "ROL_INCOMPATIBLE",
        ),
        ([{"pestana": "/cuentas", "roles": ["ASESOR", "ASESOR"]}], "ROL_DUPLICADO"),
        ([{"pestana": "/seguridad/roles", "roles": []}], "PESTANA_NO_CONFIGURABLE"),
    ],
)
def test_no_amplia_roles_ni_admite_rutas_arbitrarias(entorno, pestanas, codigo):
    cliente, base, _ = entorno
    respuesta = cliente.put(
        "/api/v1/seguridad/pestanas", json=cuerpo(cliente) | {"pestanas": pestanas}
    )
    assert respuesta.status_code == 422
    assert respuesta.json()["code"] == codigo
    assert base.filas == {}


def test_control_desactivado_conserva_contrato_anterior_y_no_consulta_sql(
    entorno, monkeypatch
):
    cliente, _, config = entorno
    config.editor_accesos_activo = False
    monkeypatch.setattr(
        accesos, "efectivos", Mock(side_effect=AssertionError("No debe consultar"))
    )
    assert "accesosSecciones" not in cliente.get("/api/v1/auth/me").json()


def test_sin_configuracion_no_concede_por_fallo(entorno, monkeypatch):
    cliente, _, _ = entorno
    monkeypatch.setattr(
        repository, "pestanas", Mock(side_effect=SQLAlchemyError("falso"))
    )
    assert (
        cliente.post("/api/v1/clientes/busqueda", json={"estado": "Activo"}).status_code
        == 503
    )


@pytest.mark.parametrize("lock", [-1, -2, -3, -999])
def test_bloqueo_impide_escritura_simultanea(entorno, lock):
    cliente, base, _ = entorno
    base.lock = lock
    respuesta = cliente.put("/api/v1/seguridad/pestanas", json=cuerpo(cliente))
    assert respuesta.status_code == (409 if lock in (-1, -2, -3) else 503)
    assert base.filas == {}


@pytest.mark.parametrize(
    "seccion,metodo,ruta",
    [(s, m, r) for s, rutas in secciones.RUTAS_POR_SECCION.items() for m, r in rutas],
)
def test_rechazo_de_cada_api_antes_de_consultar_negocio(entorno, seccion, metodo, ruta):
    cliente, base, _ = entorno
    simular_sesion(app, usuario_con_roles(*ROLES))
    base.filas[secciones.RUTAS_SECCION[seccion]] = ""
    bloqueado = Mock(side_effect=AssertionError("No consultar negocio"))
    app.dependency_overrides[cooperativa] = bloqueado
    respuesta = cliente.request(
        metodo,
        re.sub(r"\{[^}]+\}", "1", ruta),
        json={} if metodo in ("POST", "PUT", "PATCH") else None,
    )
    assert respuesta.status_code == 403, (ruta, respuesta.text)
    assert (
        respuesta.json().get("code") or respuesta.json().get("detail", {}).get("code")
    ) == "ACCESO_SECCION_RETIRADO", respuesta.text
    bloqueado.assert_not_called()


def test_cobertura_del_inventario_real_de_apis():
    pendientes = []
    for ruta, operaciones in app.openapi()["paths"].items():
        if any(ruta == p or ruta.startswith(p + "/") for p in secciones.AMBITOS):
            for metodo in operaciones:
                if (
                    metodo in ("get", "post", "put", "patch", "delete")
                    and secciones.seccion_api(
                        metodo.upper(), re.sub(r"\{[^}]+\}", "1", ruta)
                    )
                    is None
                ):
                    pendientes.append((metodo, ruta))
    assert pendientes == []
