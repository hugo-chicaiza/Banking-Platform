"""ATM-08 HTTP con JWT y credencial sinteticos; ninguna conexion SQL real."""

from datetime import UTC, datetime
from unittest.mock import MagicMock

import jwt
import pytest

from app.modules.atm import reversos_service as svc
from app.modules.atm import session
from app.modules.transacciones import service as trx_service
from app.modules.transacciones.dependencias import dependencias_operacion
from tests.integration.test_atm_transferencias_local import http  # noqa: F401 -- fixture sin SQL y con spies financieros.
from tests.unit.test_atm_api import api  # noqa: F401 -- fixture RSA y credencial efimeras.

BODY = {"idTransaccion": 70, "motivo": "TIMEOUT"}
URL = "/api/v1/atm/reversos"


@pytest.fixture
def cliente(request, monkeypatch):
    e = request.getfixturevalue("http")
    monkeypatch.setattr(svc, "prevalidar_reverso", e.prohibido)
    monkeypatch.setattr(trx_service, "reversar", e.prohibido)
    return e


def test_cerrado_sin_efectos_y_sin_datos_sensibles(cliente, caplog):
    for _ in range(2):
        r = cliente.client.post(URL, json=BODY, headers=cliente.headers)
        assert r.status_code == 501
        assert r.json()["code"] == "OPERACION_NO_HABILITADA"
        assert r.headers["content-type"].startswith("application/problem+json")
        assert r.headers["cache-control"] == "no-store"
        assert "idTransaccion" not in r.json()
        assert cliente.token not in caplog.text + r.text
        assert cliente.secret not in caplog.text + r.text
    cliente.prohibido.assert_not_called()


def test_deps_de_otro_modulo_no_habilitan(cliente):
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
def test_sesion_y_terminal_validos_son_obligatorios(cliente, caso):
    h = dict(cliente.headers)
    if caso == "ausente":
        h.pop("Authorization")
    elif caso == "invalido":
        h["Authorization"] = "Bearer falso"
    elif caso == "expirado":
        claims = jwt.decode(cliente.token, options={"verify_signature": False})
        claims["iat"] = int(datetime.now(UTC).timestamp()) - 600
        claims["exp"] = claims["iat"] + 300
        h["Authorization"] = "Bearer " + jwt.encode(
            claims, session.preparar_emisor_atm().clave, algorithm="RS256"
        )
    elif caso == "revocado":
        cliente.revocada = True
    elif caso == "version":
        cliente.pin["fecha_asignacion"] = datetime(2026, 11, 2)
    elif caso == "restringido":
        cliente.pin["requiere_cambio"] = True
    elif caso == "bloqueado":
        cliente.pin["estado_pin"] = "Bloqueado"
    elif caso == "coordinacion":
        cliente.pin["coordinacion_pendiente"] = True
    else:
        h.pop("X-ATM-Credential")
    r = cliente.client.post(URL, json=BODY, headers=h)
    assert r.status_code in (401, 403)
    cliente.prohibido.assert_not_called()


@pytest.mark.parametrize(
    "cambio",
    [
        {"idTransaccion": True},
        {"idTransaccion": -1},
        {"idTransaccion": "70"},
        {"motivo": "NO_FILTRAR_SECRETO"},
        {"registroUnico": "A1B2C3D4E5F6"},
        {"monto": 1},
    ],
)
def test_contrato_no_inventa_campos_ni_expone_errores(cliente, cambio):
    r = cliente.client.post(URL, json={**BODY, **cambio}, headers=cliente.headers)
    assert r.status_code == 400
    assert "NO_FILTRAR_SECRETO" not in r.text
    cliente.prohibido.assert_not_called()


def test_lector_acotado_y_seguro(cliente):
    h = {**cliente.headers, "Content-Type": "application/json"}
    assert (
        cliente.client.post(
            URL, content='{"idTransaccion":1,"idTransaccion":2}', headers=h
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
        cliente.client.post(URL + "?registroUnico=x", json=BODY, headers=h).status_code
        == 400
    )
    assert (
        cliente.client.post("http://testserver" + URL, json=BODY, headers=h).json()[
            "code"
        ]
        == "HTTPS_REQUERIDO"
    )
    cliente.prohibido.assert_not_called()


def test_openapi_parcial_sin_exito_ficticio(cliente):
    op = cliente.app.openapi()["paths"][URL]["post"]
    assert op["operationId"] == "ATM08"
    assert "501" in op["responses"] and not {"200", "201"} & op["responses"].keys()
    assert op["security"] == [{"SesionATM": [], "APIKeyHeader": []}]
    assert set(
        op["requestBody"]["content"]["application/json"]["schema"]["properties"]
    ) == set(BODY)
