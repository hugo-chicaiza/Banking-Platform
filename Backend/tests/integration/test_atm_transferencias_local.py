"""HTTP local: JWT RS256 y credencial reales; SQL simulado y prohibido fuera de mocks."""

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock, Mock

import jwt
import pytest

from app.modules.atm import repository, router, session
from app.modules.atm import transferencias_service as svc
from app.modules.transacciones import numeracion
from app.modules.transacciones import repository as tx_repo
from app.modules.transacciones.dependencias import dependencias_operacion
from tests.pin_version import FECHA_PIN
from tests.unit.test_atm_api import api  # noqa: F401 -- fixture de credencial/RSA sinteticos.

BODY = {
    "idCuentaOrigen": 77,
    "numeroCuentaDestino": "AH00000002",
    "monto": 150,
    "registroUnico": "A1B2C3D4E5F6",
}


@pytest.fixture
def http(request, monkeypatch):
    e = request.getfixturevalue("api")
    e.token = session.preparar_emisor_atm().emitir(e.acceso).session_token
    e.headers = {**e.headers, "Authorization": "Bearer " + e.token}
    e.pin = {
        "fecha_asignacion": FECHA_PIN,
        "tiene_pin_asignado": True,
        "estado_pin": "Activo",
        "intentos_fallidos": 0,
        "requiere_cambio": False,
        "coordinacion_pendiente": False,
    }
    e.revocada = False
    monkeypatch.setattr(session, "get_engine", MagicMock())
    monkeypatch.setattr(repository, "sesion_atm_revocada", lambda *a: e.revocada)
    monkeypatch.setattr(repository, "obtener_asignacion_pin_actual", lambda *a: e.pin)
    e.prohibido = Mock(
        side_effect=AssertionError("No debe acceder a cuentas ni efectos financieros")
    )
    monkeypatch.setattr(router, "get_engine", e.prohibido)
    monkeypatch.setattr(svc, "prevalidar_transferencia", e.prohibido)
    monkeypatch.setattr(tx_repo, "insertar_transaccion", e.prohibido)
    monkeypatch.setattr(tx_repo, "aplicar_movimiento_cuenta", e.prohibido)
    monkeypatch.setattr(numeracion, "numerar_consulta", e.prohibido)
    return e


def test_endpoint_cerrado_con_auth_real_y_sin_efectos(http, caplog):
    for _ in range(2):
        r = http.client.post(
            "/api/v1/atm/transferencias", json=BODY, headers=http.headers
        )
        assert r.status_code == 501
        assert r.json()["code"] == "OPERACION_NO_HABILITADA"
        assert r.headers["content-type"].startswith("application/problem+json")
        assert r.headers["cache-control"] == "no-store"
        assert "idTransaccion" not in r.json()
        for dato in (http.token, http.secret, BODY["numeroCuentaDestino"]):
            assert dato not in r.text + caplog.text
    http.prohibido.assert_not_called()


def test_configurar_dependencias_de_otro_modulo_no_abre_endpoint(http):
    http.app.dependency_overrides[dependencias_operacion] = lambda: MagicMock()
    r = http.client.post("/api/v1/atm/transferencias", json=BODY, headers=http.headers)
    assert r.status_code == 501
    http.prohibido.assert_not_called()


@pytest.mark.parametrize(
    "caso",
    [
        "sin_jwt",
        "jwt_invalido",
        "sin_credencial",
        "credencial_invalida",
        "revocada",
        "pin_antiguo",
        "pin_pendiente",
        "pin_bloqueado",
        "restringida",
        "expirada",
        "sin_version",
    ],
)
def test_controles_de_seguridad_se_aplican_antes_del_501(http, caso):
    headers = dict(http.headers)
    if caso == "sin_jwt":
        headers.pop("Authorization")
    elif caso == "jwt_invalido":
        headers["Authorization"] = "Bearer invalido"
    elif caso == "sin_credencial":
        headers.pop("X-ATM-Credential")
    elif caso == "credencial_invalida":
        headers["X-ATM-Credential"] = "invalida"
    elif caso == "revocada":
        http.revocada = True
    elif caso == "pin_antiguo":
        http.pin["fecha_asignacion"] = datetime(2026, 11, 2)
    elif caso == "pin_pendiente":
        http.pin["requiere_cambio"] = True
    elif caso == "pin_bloqueado":
        http.pin["estado_pin"] = "Bloqueado"
    elif caso == "restringida":
        http.pin["requiere_cambio"] = True
        restringido = replace(http.acceso, cambio_pin_requerido=True, cuentas=[])
        headers["Authorization"] = (
            "Bearer " + session.preparar_emisor_atm().emitir(restringido).session_token
        )
    else:
        claims = jwt.decode(http.token, options={"verify_signature": False})
        if caso == "expirada":
            claims["iat"] = int(datetime.now(UTC).timestamp()) - 600
            claims["exp"] = claims["iat"] + 300
        else:
            claims.pop("pinVersion")
        headers["Authorization"] = "Bearer " + jwt.encode(
            claims, session.preparar_emisor_atm().clave, algorithm="RS256"
        )
    r = http.client.post("/api/v1/atm/transferencias", json=BODY, headers=headers)
    assert r.status_code in (401, 403)
    if caso in ("restringida", "pin_pendiente"):
        assert r.json()["code"] == "PIN_CAMBIO_REQUERIDO"
    http.prohibido.assert_not_called()


def test_origen_fuera_de_sesion_se_oculta(http):
    r = http.client.post(
        "/api/v1/atm/transferencias",
        json={**BODY, "idCuentaOrigen": 999},
        headers=http.headers,
    )
    assert r.status_code == 404
    http.prohibido.assert_not_called()


@pytest.mark.parametrize(
    "datos",
    [
        {"monto": 0},
        {"monto": -1},
        {"monto": 1.001},
        {"moneda": "EUR"},
        {"comision": 0},
        {"numeroCuentaDestino": "SENSIBLE_NO_DEVOLVER_" + "X" * 40},
    ],
)
def test_entrada_invalida_no_expone_datos_ni_consulta_cuentas(http, datos):
    r = http.client.post(
        "/api/v1/atm/transferencias", json={**BODY, **datos}, headers=http.headers
    )
    # F-04 usa 400 DATOS_INVALIDOS para errores estructurales de entrada.
    assert r.status_code == 400
    assert "SENSIBLE_NO_DEVOLVER" not in r.text
    http.prohibido.assert_not_called()


def test_openapi_declara_barrera_sin_exito_ficticio(http):
    op = http.app.openapi()["paths"]["/api/v1/atm/transferencias"]["post"]
    assert op["operationId"] == "ATM05"
    assert "501" in op["responses"] and not {"200", "201"} & op["responses"].keys()
    assert op["security"] == [{"SesionATM": [], "APIKeyHeader": []}]
    schema = op["requestBody"]["content"]["application/json"]["schema"]
    assert set(schema["properties"]) == set(BODY)


def test_importe_json_no_pierde_centavos_por_float(http, monkeypatch):
    capturada = []

    def cerrado(sesion, terminal, entrada, deps):
        capturada.append(entrada)
        raise svc.no_habilitada()

    monkeypatch.setattr(svc, "solicitar_transferencia", cerrado)
    raw = '{"idCuentaOrigen":77,"numeroCuentaDestino":"AH00000002","monto":9999999999999999.99,"registroUnico":"A1B2C3D4E5F6"}'
    r = http.client.post(
        "/api/v1/atm/transferencias",
        content=raw,
        headers={**http.headers, "Content-Type": "application/json"},
    )
    assert r.status_code == 501
    assert capturada[0].monto == Decimal("9999999999999999.99")


def test_json_duplicado_o_query_se_rechazan(http):
    raw = '{"idCuentaOrigen":77,"idCuentaOrigen":9}'
    assert (
        http.client.post(
            "/api/v1/atm/transferencias",
            content=raw,
            headers={**http.headers, "Content-Type": "application/json"},
        ).status_code
        == 400
    )
    assert (
        http.client.post(
            "/api/v1/atm/transferencias?monto=1", json=BODY, headers=http.headers
        ).status_code
        == 400
    )
    http.prohibido.assert_not_called()


@pytest.mark.parametrize("caso,estado", [("http", 400), ("tipo", 415), ("tamano", 413)])
def test_transporte_y_cuerpo_acotados(http, caso, estado):
    url = "/api/v1/atm/transferencias"
    headers = {**http.headers, "Content-Type": "application/json"}
    content = "{}"
    if caso == "http":
        url = "http://testserver" + url
    elif caso == "tipo":
        headers["Content-Type"] = "text/plain"
    else:
        content = " " * 2049
    r = http.client.post(url, content=content, headers=headers)
    assert r.status_code == estado
    if caso == "http":
        # require_sesion_atm rechaza HTTP con el contrato existente 400.
        assert r.json()["code"] == "HTTPS_REQUERIDO"
    http.prohibido.assert_not_called()
