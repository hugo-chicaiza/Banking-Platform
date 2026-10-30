"""Pruebas unitarias de CTA-01 · POST /api/v1/cuentas.

No requieren base de datos: se monkeypatcha el repositorio.

Autenticación (F-03): require_auth() aún no valida JWT; el rechazo
sin token (401) no se puede probar hasta que F-03 esté implementado.
"""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.core.db import cooperativa
from app.main import app
from app.modules.cuentas import repository, service

# ---------------------------------------------------------------------------
# Stubs de conexión
# ---------------------------------------------------------------------------


class _FakeConn:
    """Objeto stub que satisface los calls a conn.commit() / conn.rollback()."""

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass


@pytest.fixture()
def client():
    """Cliente HTTP sin base de datos; inyecta None como conexión."""
    app.dependency_overrides[cooperativa] = lambda: None
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture()
def client_with_fakeconn():
    """Cliente HTTP sin base de datos; inyecta FakeConn (tiene commit/rollback)."""
    app.dependency_overrides[cooperativa] = lambda: _FakeConn()
    yield TestClient(app)
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Datos de stub reutilizables
# ---------------------------------------------------------------------------

_CLIENTE_ACTIVO = {"estado": "Activo"}
_RIESGO_APROBADO = {"estado": "Aprobado"}
_PRODUCTO_CUENTA = {
    "tipo_producto": "Cuenta",
    "estado": "A",
    "monto_apertura_minimo": Decimal("50.00"),
}
_AGENCIA_ACTIVA = {"estado": "A"}
_CUENTA_DB = {
    "id_cuenta": 501,
    "numero_cuenta": "AH00000001",
    "id_cliente": 125,
    "id_producto": 2,
    "id_agencia": "001",
    "tipo_cuenta": "Ahorro",
    "id_moneda": 840,
    "saldo": Decimal("0.00"),
    "saldo_retenido": Decimal("0.00"),
    "estado": "PENDIENTE_ACTIVACION",
}

_PAYLOAD = {
    "idCliente": 125,
    "idProducto": 2,
    "idAgencia": "001",
    "tipoCuenta": "Ahorro",
    "idMoneda": 840,
}


def _patch_repo(
    monkeypatch, *, cliente=None, riesgo=None, producto=None, agencia=None, cuenta=None
):
    """Aplica stubs al módulo repository para el caso de prueba indicado."""
    monkeypatch.setattr(repository, "obtener_cliente", lambda conn, _id: cliente)
    monkeypatch.setattr(repository, "obtener_riesgo_vigente", lambda conn, _id: riesgo)
    monkeypatch.setattr(repository, "obtener_producto", lambda conn, _id: producto)
    monkeypatch.setattr(repository, "obtener_agencia", lambda conn, _id: agencia)
    monkeypatch.setattr(repository, "abrir_cuenta", lambda *args, **kw: cuenta)


# ---------------------------------------------------------------------------
# Caso feliz
# ---------------------------------------------------------------------------


def test_abrir_cuenta_201(client_with_fakeconn, monkeypatch):
    _patch_repo(
        monkeypatch,
        cliente=_CLIENTE_ACTIVO,
        riesgo=_RIESGO_APROBADO,
        producto=_PRODUCTO_CUENTA,
        agencia=_AGENCIA_ACTIVA,
        cuenta=_CUENTA_DB,
    )
    monkeypatch.setattr(
        service, "_generar_numero_cuenta", lambda conn, tipo, prod: "AH00000001"
    )

    r = client_with_fakeconn.post("/api/v1/cuentas", json=_PAYLOAD)

    assert r.status_code == 201
    body = r.json()
    assert body["idCuenta"] == 501
    assert body["numeroCuenta"] == "AH00000001"
    assert body["estado"] == "PENDIENTE_ACTIVACION"
    assert body["saldo"] == 0.0
    assert body["saldoRetenido"] == 0.0


# ---------------------------------------------------------------------------
# 409 CLIENTE_NO_ACTIVO · cliente inexistente
# ---------------------------------------------------------------------------


def test_cliente_no_existe_409(client, monkeypatch):
    _patch_repo(monkeypatch, cliente=None)

    r = client.post("/api/v1/cuentas", json=_PAYLOAD)

    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "CLIENTE_NO_ACTIVO"


# ---------------------------------------------------------------------------
# 409 CLIENTE_NO_ACTIVO · cliente en estado distinto de Activo
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("estado", ["Pendiente", "Bloqueado", "Inactivo", "Cerrado"])
def test_cliente_no_activo_409(client, monkeypatch, estado):
    _patch_repo(monkeypatch, cliente={"estado": estado})

    r = client.post("/api/v1/cuentas", json=_PAYLOAD)

    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "CLIENTE_NO_ACTIVO"


# ---------------------------------------------------------------------------
# 409 RIESGO_RECHAZADO
# ---------------------------------------------------------------------------


def test_riesgo_rechazado_409(client, monkeypatch):
    _patch_repo(
        monkeypatch,
        cliente=_CLIENTE_ACTIVO,
        riesgo={"estado": "Rechazado"},
    )

    r = client.post("/api/v1/cuentas", json=_PAYLOAD)

    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "RIESGO_RECHAZADO"


# ---------------------------------------------------------------------------
# 422 PRODUCTO_NO_ES_CUENTA · producto inexistente
# ---------------------------------------------------------------------------


def test_producto_inexistente_422(client, monkeypatch):
    _patch_repo(
        monkeypatch,
        cliente=_CLIENTE_ACTIVO,
        riesgo=_RIESGO_APROBADO,
        producto=None,
    )

    r = client.post("/api/v1/cuentas", json=_PAYLOAD)

    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "PRODUCTO_NO_ES_CUENTA"


# ---------------------------------------------------------------------------
# 422 PRODUCTO_NO_ES_CUENTA · tipo distinto de Cuenta
# ---------------------------------------------------------------------------


def test_producto_tipo_incorrecto_422(client, monkeypatch):
    _patch_repo(
        monkeypatch,
        cliente=_CLIENTE_ACTIVO,
        riesgo=_RIESGO_APROBADO,
        producto={
            "tipo_producto": "Tarjeta",
            "estado": "A",
            "monto_apertura_minimo": Decimal(0),
        },
    )

    r = client.post("/api/v1/cuentas", json=_PAYLOAD)

    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "PRODUCTO_NO_ES_CUENTA"


# ---------------------------------------------------------------------------
# 422 PRODUCTO_NO_ES_CUENTA · producto inactivo
# ---------------------------------------------------------------------------


def test_producto_inactivo_422(client, monkeypatch):
    _patch_repo(
        monkeypatch,
        cliente=_CLIENTE_ACTIVO,
        riesgo=_RIESGO_APROBADO,
        producto={
            "tipo_producto": "Cuenta",
            "estado": "I",
            "monto_apertura_minimo": Decimal(0),
        },
    )

    r = client.post("/api/v1/cuentas", json=_PAYLOAD)

    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "PRODUCTO_NO_ES_CUENTA"


# ---------------------------------------------------------------------------
# 409 AGENCIA_INACTIVA · agencia inexistente
# ---------------------------------------------------------------------------


def test_agencia_no_existe_409(client, monkeypatch):
    _patch_repo(
        monkeypatch,
        cliente=_CLIENTE_ACTIVO,
        riesgo=_RIESGO_APROBADO,
        producto=_PRODUCTO_CUENTA,
        agencia=None,
    )

    r = client.post("/api/v1/cuentas", json=_PAYLOAD)

    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "AGENCIA_INACTIVA"


# ---------------------------------------------------------------------------
# 409 AGENCIA_INACTIVA · agencia en estado distinto de A
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("estado", ["I", "C"])
def test_agencia_inactiva_409(client, monkeypatch, estado):
    _patch_repo(
        monkeypatch,
        cliente=_CLIENTE_ACTIVO,
        riesgo=_RIESGO_APROBADO,
        producto=_PRODUCTO_CUENTA,
        agencia={"estado": estado},
    )

    r = client.post("/api/v1/cuentas", json=_PAYLOAD)

    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "AGENCIA_INACTIVA"


# ---------------------------------------------------------------------------
# 400 · validación de campo (FastAPI)
# ---------------------------------------------------------------------------


def test_payload_invalido_400(client):
    """idAgencia de más de 3 caracteres debe rechazarse en 422 por Pydantic."""
    payload = {**_PAYLOAD, "idAgencia": "TOOLONG"}

    r = client.post("/api/v1/cuentas", json=payload)

    # FastAPI devuelve 422 (Unprocessable Entity) para errores de validación
    assert r.status_code == 422


def test_payload_sin_campos_requeridos_400(client):
    r = client.post("/api/v1/cuentas", json={})

    assert r.status_code == 422


# ---------------------------------------------------------------------------
# TODO(F-03): test_sin_token_401
# Probar rechazo sin token depende de que require_auth() valide el JWT.
# ---------------------------------------------------------------------------
