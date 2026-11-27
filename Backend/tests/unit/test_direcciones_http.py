"""El HTTP conserva la identidad del operador y el contrato del catálogo nuevo."""

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.core.database.db import cooperativa
from app.core.security.auth import id_usuario_auditoria
from app.main import app
from app.modules.clientes import router as cliente_router
from app.modules.clientes import service
from app.modules.clientes.schemas import Cliente, Direccion
from app.modules.seguridad import funciones
from tests.sesion import simular_sesion, usuario_con_roles
from tests.unit.test_direcciones_persistencia import payload


@pytest.fixture
def http(monkeypatch):
    simular_sesion(app, usuario_con_roles("ADMIN"))
    app.dependency_overrides[cooperativa] = lambda: MagicMock()
    app.dependency_overrides[id_usuario_auditoria] = lambda: 7
    monkeypatch.setattr(funciones, "activa", lambda: False)
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def test_http_registro_transmite_identidad_y_devuelve_direccion_principal(
    http, monkeypatch
):
    entrada = payload()
    ahora = datetime.now(UTC)
    cliente = Cliente.model_validate(
        {
            **entrada.model_dump(exclude={"direccion"}),
            "id_cliente": 91,
            "fecha_consentimiento": ahora,
            "fecha_registro": ahora,
            "estado": "Pendiente",
            "creado_por": 7,
            "direcciones": [
                {
                    **entrada.direccion.model_dump(),
                    "id_direccion": 42,
                    "estado": "Activo",
                }
            ],
        }
    )
    guardar = MagicMock(return_value=cliente)
    monkeypatch.setattr(service, "registrar_cliente", guardar)
    respuesta = http.post(
        "/api/v1/clientes", json=entrada.model_dump(mode="json", by_alias=True)
    )
    assert respuesta.status_code == 201
    assert respuesta.json()["direcciones"][0]["tipoDireccion"] == "Temporal"
    assert guardar.call_args is not None
    assert guardar.call_args.args[2] == 7


def test_http_alta_y_edicion_conservan_cliente_direccion_y_actor(http, monkeypatch):
    entrada = payload().direccion
    fila = Direccion.model_validate(
        {**entrada.model_dump(), "id_direccion": 42, "estado": "Activo"}
    )
    alta = MagicMock(return_value=fila)
    editar = MagicMock(return_value=fila)
    monkeypatch.setattr(service, "agregar_direccion", alta)
    monkeypatch.setattr(service, "editar_direccion", editar)
    respuesta = http.post(
        "/api/v1/clientes/91/direcciones",
        json=entrada.model_dump(mode="json", by_alias=True),
    )
    assert respuesta.status_code == 201
    assert alta.call_args is not None
    assert alta.call_args.args[1] == 91
    assert alta.call_args.args[3] == 7
    respuesta = http.patch("/api/v1/clientes/91/direcciones/42", json={"sector": None})
    assert respuesta.status_code == 200
    assert editar.call_args is not None
    assert editar.call_args.args[1:3] == (91, 42)
    assert editar.call_args.args[4] == 7
    assert editar.call_args.args[3].model_dump(exclude_unset=True) == {"sector": None}


def test_http_validacion_documento_no_altera_el_contrato_existente(http, monkeypatch):
    validar = MagicMock(
        return_value={"valida": True, "existe": False, "mensaje": "Disponible"}
    )
    monkeypatch.setattr(service, "validar_identificacion", validar)
    # El documento va en el cuerpo, nunca en la URL (ASVS 14.2.1).
    respuesta = http.post(
        "/api/v1/clientes/validaciones/documento",
        json={"tipoDocumento": "C", "identificacion": "0100000025"},
    )
    assert respuesta.status_code == 200
    assert respuesta.json()["existe"] is False


def test_fallo_al_comprobar_visibilidad_no_guarda_antes_de_responder_error(
    http, monkeypatch
):
    def no_disponible(usuario):
        raise HTTPException(503, "Accesos no disponibles")

    guardar = MagicMock()
    monkeypatch.setattr(cliente_router, "puede_ver_direcciones", no_disponible)
    monkeypatch.setattr(service, "registrar_cliente", guardar)
    respuesta = http.post(
        "/api/v1/clientes", json=payload().model_dump(mode="json", by_alias=True)
    )
    assert respuesta.status_code == 503
    guardar.assert_not_called()
