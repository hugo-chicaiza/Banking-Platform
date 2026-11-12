from contextlib import contextmanager
from unittest.mock import MagicMock, Mock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.core.database.db import cooperativa
from app.core.security import audit
from app.core.security.auth import normalizar_roles
from app.modules.organizacion import repository, service
from app.modules.organizacion.router import router
from tests.sesion import simular_sesion, usuario_con_roles

RUTA = "/api/v1/agencias/001/estado"


@pytest.fixture
def ctx(monkeypatch):
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    conn = MagicMock()
    conn.in_transaction.return_value = True
    app.dependency_overrides[cooperativa] = lambda: conn
    simular_sesion(app, usuario_con_roles("ADMIN"))
    leer = Mock(return_value={"id_agencia": "001", "estado": "A"})
    escribir = Mock(return_value=True)
    auditoria = Mock()
    monkeypatch.setattr(repository, "bloquear_agencia", leer)
    monkeypatch.setattr(
        repository,
        "obtener_agencia",
        Mock(return_value={"TipoAgencia": "Sucursal"}),
    )
    monkeypatch.setattr(
        repository,
        "dependencias_activas",
        Mock(return_value=[]),
    )
    monkeypatch.setattr(repository, "actualizar_estado", escribir)
    monkeypatch.setattr(audit, "registrar", auditoria)
    with TestClient(app) as cliente:
        yield app, cliente, conn, leer, escribir, auditoria


@pytest.mark.parametrize("anterior,nuevo", [("A", "I"), ("I", "A")])
def test_admin_activa_y_desactiva(ctx, anterior, nuevo):
    _, cliente, conn, leer, escribir, auditoria = ctx
    leer.return_value = {"id_agencia": "001", "estado": anterior}
    r = cliente.patch(RUTA, json={"estado": nuevo})
    assert r.status_code == 200, r.text
    assert r.json() == {"idAgencia": "001", "estado": nuevo}
    assert r.headers["cache-control"] == "no-store"
    leer.assert_called_once_with(conn, "001")
    escribir.assert_called_once_with(conn, "001", anterior, nuevo)
    auditoria.assert_called_once()
    conn.begin.return_value.__exit__.assert_called_once_with(None, None, None)


@pytest.mark.parametrize("estado", ["A", "I", "C"])
def test_repetir_no_escribe_ni_repite_auditoria(ctx, estado):
    _, cliente, _, leer, escribir, auditoria = ctx
    leer.return_value = {"id_agencia": "001", "estado": estado}
    for _ in range(2):
        r = cliente.patch(RUTA, json={"estado": estado})
        assert r.status_code == 200 and r.json()["estado"] == estado
    escribir.assert_not_called()
    auditoria.assert_not_called()


@pytest.mark.parametrize(
    "anterior,nuevo", [("C", "A"), ("C", "I"), ("A", "C"), ("I", "C")]
)
def test_reapertura_y_cierre_no_habilitados(ctx, anterior, nuevo):
    _, cliente, conn, leer, escribir, _ = ctx
    leer.return_value = {"id_agencia": "001", "estado": anterior}
    r = cliente.patch(RUTA, json={"estado": nuevo})
    assert r.status_code == 409
    escribir.assert_not_called()
    assert conn.begin.return_value.__exit__.call_args.args[0] is HTTPException


def test_agencia_inexistente(ctx):
    _, cliente, _, leer, escribir, _ = ctx
    leer.return_value = None
    r = cliente.patch(RUTA, json={"estado": "I"})
    assert r.status_code == 404 and r.json()["code"] == "AGENCIA_NO_ENCONTRADA"
    escribir.assert_not_called()


@pytest.mark.parametrize(
    "roles",
    [
        ("CONTADOR",),
        ("SUPERVISOR",),
        ("CAJERO",),
        ("ASESOR",),
        ("AUDITOR",),
        (),
        normalizar_roles(["org-contador"], None),
    ],
)
def test_sin_rol_administrativo_no_toca_bd(ctx, roles):
    app, cliente, conn, leer, escribir, _ = ctx
    simular_sesion(app, usuario_con_roles(*roles))
    r = cliente.patch(RUTA, json={"estado": "I"})
    assert r.status_code == 403 and r.json()["code"] == "SIN_PERMISO"
    leer.assert_not_called()
    escribir.assert_not_called()
    conn.begin.assert_not_called()


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"estado": "Activo"},
        {"estado": "i"},
        {"estado": None},
        {"estado": 1},
        {"estado": "I", "nombre": "otro"},
        {"estado": "A", "idAgencia": "002"},
    ],
)
def test_body_solo_estado(ctx, payload):
    _, cliente, conn, leer, escribir, _ = ctx
    r = cliente.patch(RUTA, json=payload)
    assert r.status_code == 400
    leer.assert_not_called()
    escribir.assert_not_called()
    conn.begin.assert_not_called()


def test_actualizacion_no_confirmada_no_informa_exito(ctx):
    _, cliente, _, _, escribir, auditoria = ctx
    escribir.return_value = False
    r = cliente.patch(RUTA, json={"estado": "I"})
    assert r.status_code == 409
    auditoria.assert_not_called()


@pytest.mark.parametrize("flujo", ["alta_asociada", "asignacion_existente"])
@pytest.mark.parametrize("estado", ["A", "I", "C"])
def test_guard_antes_de_workos_y_escritura_local(ctx, flujo, estado):
    _, _, conn, leer, _, _ = ctx
    orden = []
    leer.side_effect = lambda *a: (
        orden.append("agencia"),
        {"id_agencia": "001", "estado": estado},
    )[1]
    workos = Mock(side_effect=lambda: orden.append("workos"))
    guardar = Mock(side_effect=lambda: orden.append("guardar"))

    # Contrato de integración: AUT-06/AUT-11 todavía no tienen servicio real.
    # Ninguna invitación ni alta WorkOS se ejecuta en esta prueba.
    @contextmanager
    def flujo_futuro():
        with conn.begin():
            service.exigir_agencia_destino_activa(conn, "001")
            yield

    def ejecutar():
        with flujo_futuro():
            if flujo == "alta_asociada":
                workos()
            guardar()

    if estado == "A":
        ejecutar()
        assert orden == (
            ["agencia", "workos", "guardar"]
            if flujo == "alta_asociada"
            else ["agencia", "guardar"]
        )
        guardar.assert_called_once()
    else:
        with pytest.raises(HTTPException) as error:
            ejecutar()
        assert error.value.status_code == 409
        workos.assert_not_called()
        guardar.assert_not_called()
        assert orden == ["agencia"]


def test_guard_no_permite_validar_fuera_de_transaccion(ctx):
    _, _, conn, leer, _, _ = ctx
    conn.in_transaction.return_value = False
    with pytest.raises(RuntimeError, match="transacción"):
        service.exigir_agencia_destino_activa(conn, "001")
    leer.assert_not_called()


def test_slugs_no_amplian_permisos():
    assert normalizar_roles(["admin"], None) == ("ADMIN",)
    assert normalizar_roles(["org-contador"], None) == ("CONTADOR",)
    assert normalizar_roles(["contador"], None) == ("CONTADOR",)


def test_no_desactivar_matriz(ctx, monkeypatch):
    _, cliente, _, _, escribir, auditoria = ctx

    monkeypatch.setattr(
        repository,
        "obtener_agencia",
        Mock(return_value={"TipoAgencia": "Matriz"}),
    )

    respuesta = cliente.patch(RUTA, json={"estado": "I"})

    assert respuesta.status_code == 409
    assert respuesta.json()["code"] == "MATRIZ_NO_DESACTIVABLE"
    escribir.assert_not_called()
    auditoria.assert_not_called()


def test_no_desactivar_agencia_con_actividad(ctx, monkeypatch):
    _, cliente, _, _, escribir, auditoria = ctx

    monkeypatch.setattr(
        repository,
        "dependencias_activas",
        Mock(return_value=["Caja.JornadasCaja"]),
    )

    respuesta = cliente.patch(RUTA, json={"estado": "I"})

    assert respuesta.status_code == 409
    assert respuesta.json()["code"] == "AGENCIA_CON_ACTIVIDAD"
    escribir.assert_not_called()
    auditoria.assert_not_called()
