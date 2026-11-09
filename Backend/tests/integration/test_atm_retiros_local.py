"""ATM-03 HTTP: JWT/credencial sinteticos, sin SQL ni efectos financieros."""

from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from app.modules.atm import retiros_service as svc
from app.modules.transacciones.dependencias import dependencias_operacion
from tests.integration.atm_http_scenarios import preparar_fallo_autenticacion
from tests.integration.test_atm_transferencias_local import http  # noqa: F401 -- fixture con spies de escritores y SQL prohibido.
from tests.unit.test_atm_api import api  # noqa: F401 -- RSA/credencial efimeras.

URL = "/api/v1/atm/retiros"
BODY = {"idCuenta": 77, "monto": 150, "registroUnico": "A1B2C3D4E5F6"}


@pytest.fixture
def cliente(request, monkeypatch):
    e = request.getfixturevalue("http")
    monkeypatch.setattr(svc, "prevalidar_retiro", e.prohibido)
    monkeypatch.setattr(svc.repo, "leer_gavetas", e.prohibido)
    return e


def test_cerrado_sin_debito_reserva_ni_comprobante(cliente, caplog):
    for _ in range(2):
        r = cliente.client.post(URL, json=BODY, headers=cliente.headers)
        assert r.status_code == 501 and r.json()["code"] == "OPERACION_NO_HABILITADA"
        assert r.headers["content-type"].startswith("application/problem+json")
        assert r.headers["cache-control"] == "no-store"
        assert "idTransaccion" not in r.json()
        assert cliente.token not in caplog.text + r.text
        assert cliente.secret not in caplog.text + r.text
    cliente.prohibido.assert_not_called()


def test_dependencias_de_otro_modulo_no_habilitan(cliente):
    cliente.app.dependency_overrides[dependencias_operacion] = lambda: MagicMock()
    assert (
        cliente.client.post(URL, json=BODY, headers=cliente.headers).status_code == 501
    )
    cliente.prohibido.assert_not_called()


@pytest.mark.parametrize(
    "caso",
    [
        "ausente",
        "invalido",
        "expirado",
        "revocado",
        "version",
        "restringido",
        "bloqueado",
        "coordinacion",
        "credencial",
    ],
)
def test_seguridad_se_aplica_antes_del_501(cliente, caso):
    h = preparar_fallo_autenticacion(cliente, caso)
    r = cliente.client.post(URL, json=BODY, headers=h)
    assert r.status_code in (401, 403)
    cliente.prohibido.assert_not_called()


def test_origen_fuera_de_sesion(cliente):
    assert (
        cliente.client.post(
            URL, json={**BODY, "idCuenta": 999}, headers=cliente.headers
        ).status_code
        == 404
    )
    cliente.prohibido.assert_not_called()


@pytest.mark.parametrize(
    "cambio",
    [
        {"monto": True},
        {"monto": 0},
        {"monto": 1.001},
        {"moneda": "EUR"},
        {"exonerada": True},
        {"fechaHoraDispositivo": "NO_FILTRAR_SECRETO"},
    ],
)
def test_entrada_estricta_no_expone_valores(cliente, cambio):
    r = cliente.client.post(URL, json={**BODY, **cambio}, headers=cliente.headers)
    assert r.status_code == 400 and "NO_FILTRAR_SECRETO" not in r.text
    cliente.prohibido.assert_not_called()


def test_lector_json_seguro(cliente):
    h = {**cliente.headers, "Content-Type": "application/json"}
    assert (
        cliente.client.post(
            URL, content='{"idCuenta":1,"idCuenta":2}', headers=h
        ).status_code
        == 400
    )
    assert cliente.client.post(URL, content=" " * 2049, headers=h).status_code == 413
    assert (
        cliente.client.post(
            URL, content="{}", headers={**h, "Content-Type": "text/plain"}
        ).status_code
        == 415
    )
    assert (
        cliente.client.post(URL + "?monto=1", json=BODY, headers=h).status_code == 400
    )
    assert (
        cliente.client.post("http://testserver" + URL, json=BODY, headers=h).json()[
            "code"
        ]
        == "HTTPS_REQUERIDO"
    )
    cliente.prohibido.assert_not_called()


def test_importe_exacto_y_fecha_opcional(cliente, monkeypatch):
    capturada = []

    def cerrado(sesion, terminal, entrada, deps):
        capturada.append(entrada)
        raise svc.no_habilitada()

    monkeypatch.setattr(svc, "solicitar_retiro", cerrado)
    raw = '{"idCuenta":77,"monto":9999999999999999.99,"registroUnico":"A1B2C3D4E5F6","fechaHoraDispositivo":"2026-11-09T12:30:00-05:00"}'
    assert (
        cliente.client.post(
            URL,
            content=raw,
            headers={**cliente.headers, "Content-Type": "application/json"},
        ).status_code
        == 501
    )
    assert capturada[0].monto == Decimal("9999999999999999.99")
    assert capturada[0].fecha_hora_dispositivo.hour == 12


def test_openapi_sin_exito_ficticio(cliente):
    op = cliente.app.openapi()["paths"][URL]["post"]
    assert op["operationId"] == "ATM03"
    assert "501" in op["responses"] and not {"200", "201"} & op["responses"].keys()
    assert op["security"] == [{"SesionATM": [], "APIKeyHeader": []}]
    schema = op["requestBody"]["content"]["application/json"]["schema"]
    assert set(schema["properties"]) == set(BODY) | {"fechaHoraDispositivo"}
