"""Integración HTTP local: credencial y JWT reales; SQL y servicio simulados."""

import hashlib
import json
import secrets
from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.exc import SQLAlchemyError

from app.core.api.errors import problema
from app.core.config.settings import Settings
from app.core.security.hsm import HsmNoDisponible, HsmSimulado
from app.modules.atm import repository, router, service, session, terminal_auth
from app.modules.atm.schemas import CuentaATM
from app.modules.tarjetas import repository as tarjetas_repository
from app.modules.tarjetas import service as tarjetas_service
from app.modules.tarjetas.identificacion import hash_pan
from app.modules.tarjetas.schemas import TarjetaCreate, TarjetaEstadoUpdate
from tests.tarjetas_hsm import HSM, PAN, instalar, pin_generado
from tests.unit.test_tarjetas import CUENTA, FILA, PAYLOAD, SUBPRODUCTO

ACCESO_REAL = service.validar_acceso_atm

BODY = {
    "codigoATM": "ATM00001",
    "numeroTarjeta": "5000001234567896",
    "encryptedPinBlock": "A" * 32,
    "keyReference": "TEST-KEY-01",
}


@pytest.fixture
def api(tmp_path, monkeypatch):
    e = MagicMock()
    clave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    e.publica = clave.public_key()
    pem = clave.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    e.id = secrets.token_urlsafe(12)
    e.secret = secrets.token_urlsafe(32)
    e.credential = e.id + "." + e.secret
    ahora = datetime.now(UTC)
    e.path = tmp_path / "registry.json"
    e.registry = {
        e.id: {
            "codigoATM": "ATM00001",
            "sha256": hashlib.sha256(e.secret.encode()).hexdigest(),
            "enabled": True,
            "notBefore": (ahora - timedelta(minutes=1)).isoformat(),
            "expiresAt": (ahora + timedelta(days=1)).isoformat(),
            "auditUserId": 900,
        }
    }
    e.path.write_text(json.dumps(e.registry), encoding="utf-8")
    e.settings = Settings.model_construct(
        atm_terminal_credentials_file=str(e.path),
        atm_jwt_private_key_pem=SecretStr(pem),
        atm_jwt_issuer="urn:test:atm",
        atm_jwt_audience="urn:test:operations",
    )
    monkeypatch.setattr(terminal_auth, "get_settings", lambda: e.settings)
    monkeypatch.setattr(session, "get_settings", lambda: e.settings)
    e.engine = MagicMock()
    e.get_engine = MagicMock(return_value=e.engine)
    monkeypatch.setattr(router, "get_engine", e.get_engine)
    e.acceso = service.AccesoATMValidado(
        10,
        301,
        "Titular de prueba",
        [
            CuentaATM(
                id_cuenta=77,
                numero_cuenta_enmascarado="******1234",
                tipo_cuenta="Ahorro",
            ),
        ],
    )
    e.service = AsyncMock(return_value=e.acceso)
    monkeypatch.setattr(service, "validar_acceso_atm", e.service)
    app = FastAPI()
    app.include_router(router.router, prefix="/api/v1")
    e.app = app
    e.client = TestClient(app, base_url="https://testserver")
    e.headers = {"X-ATM-Credential": e.credential}
    return e


def test_http_completo_emite_rs256_cinco_minutos_sin_datos_sensibles(api, caplog):
    e = api
    respuesta = e.client.post("/api/v1/atm/auth", json=BODY, headers=e.headers)
    assert respuesta.status_code == 200, respuesta.text
    datos = respuesta.json()
    claims = jwt.decode(
        datos["sessionToken"],
        e.publica,
        algorithms=["RS256"],
        issuer="urn:test:atm",
        audience="urn:test:operations",
    )
    assert claims["exp"] - claims["iat"] == 300
    assert datos["expiresIn"] == 300
    assert respuesta.headers["cache-control"] == "no-store"
    assert jwt.get_unverified_header(datos["sessionToken"])["alg"] == "RS256"
    assert e.service.await_count == 1
    assert e.service.call_args.kwargs["usuario_bloqueo"] == 900
    for secreto in (BODY["numeroTarjeta"], BODY["encryptedPinBlock"], e.secret):
        assert secreto not in json.dumps(claims)
        assert secreto not in respuesta.text
        assert secreto not in caplog.text


@pytest.mark.parametrize(
    "caso", ["ausente", "incorrecta", "duplicada", "revocada", "caducada", "otro_atm"]
)
def test_terminal_rechazado_antes_de_sql_o_pin(api, caso):
    e = api
    headers = e.headers
    body = dict(BODY)
    if caso == "ausente":
        headers = {}
    elif caso == "incorrecta":
        headers = {"X-ATM-Credential": e.id + "." + secrets.token_urlsafe(32)}
    elif caso == "duplicada":
        headers = [("X-ATM-Credential", e.credential)] * 2
    elif caso == "revocada":
        e.registry[e.id]["enabled"] = False
    elif caso == "caducada":
        e.registry[e.id]["expiresAt"] = (
            datetime.now(UTC) - timedelta(seconds=1)
        ).isoformat()
    else:
        body["codigoATM"] = "ATM00002"
    e.path.write_text(json.dumps(e.registry), encoding="utf-8")
    respuesta = e.client.post("/api/v1/atm/auth", json=body, headers=headers)
    assert respuesta.status_code == 401
    e.get_engine.assert_not_called()
    e.service.assert_not_awaited()
    assert e.secret not in respuesta.text


def test_http_no_confia_en_forwarded_proto(api):
    e = api
    client = TestClient(e.app, base_url="http://testserver")
    respuesta = client.post(
        "/api/v1/atm/auth",
        json=BODY,
        headers={**e.headers, "X-Forwarded-Proto": "https"},
    )
    assert respuesta.status_code == 403
    e.get_engine.assert_not_called()


def test_sin_credencial_no_procesa_json_invalido(api):
    respuesta = api.client.post("/api/v1/atm/auth", content=b"not-json")
    assert respuesta.status_code == 401
    api.get_engine.assert_not_called()


def test_clave_jwt_ausente_falla_antes_de_pin(api):
    api.settings.atm_jwt_private_key_pem = SecretStr("")
    respuesta = api.client.post("/api/v1/atm/auth", json=BODY, headers=api.headers)
    assert respuesta.status_code == 503
    api.get_engine.assert_not_called()
    api.service.assert_not_awaited()


def test_revocacion_durante_pin_impide_emitir_jwt(api):
    async def revocar(*args, **kwargs):
        api.registry[api.id]["enabled"] = False
        api.path.write_text(json.dumps(api.registry), encoding="utf-8")
        return api.acceso

    api.service.side_effect = revocar
    respuesta = api.client.post("/api/v1/atm/auth", json=BODY, headers=api.headers)
    assert respuesta.status_code == 401
    assert "sessionToken" not in respuesta.json()


@pytest.mark.parametrize(
    "status,code",
    [
        (401, "PIN_INCORRECTO"),
        (423, "PIN_BLOQUEADO"),
        (422, "PIN_BLOCK_INVALIDO"),
        (503, "HSM_NO_DISPONIBLE"),
        (409, "CUENTA_NO_ACTIVA"),
    ],
)
def test_errores_servicio_no_emiten_sesion(api, status, code):
    api.service.side_effect = problema(status, code, "Autenticación rechazada.")
    respuesta = api.client.post("/api/v1/atm/auth", json=BODY, headers=api.headers)
    assert respuesta.status_code == status
    assert respuesta.json()["code"] == code
    assert "sessionToken" not in respuesta.json()
    assert respuesta.headers["cache-control"] == "no-store"


def test_openapi_documenta_contrato_y_credencial(api):
    esquema = api.app.openapi()
    operacion = esquema["paths"]["/api/v1/atm/auth"]["post"]
    assert operacion["operationId"] == "ATM01"
    assert operacion["security"]
    campos = operacion["requestBody"]["content"]["application/json"]["schema"][
        "properties"
    ]
    assert set(campos) == set(BODY)
    assert (
        esquema["components"]["securitySchemes"]["APIKeyHeader"]["name"]
        == "X-ATM-Credential"
    )


@pytest.fixture
def cadena(api, monkeypatch):
    """Criptografía y orquestación reales; persistencia exclusivamente en mocks."""
    e = api
    monkeypatch.setattr(service, "validar_acceso_atm", ACCESO_REAL)
    monkeypatch.setattr(service, "get_engine", e.get_engine)
    e.hsm = HsmSimulado(
        clave_pan=bytes(range(32)),
        clave_pvk=bytes(range(100, 116)),
        claves_pin_block={"TEST-KEY-01": bytes(range(32, 64))},
        referencia_pin_block="TEST-KEY-01",
    )
    monkeypatch.setattr(service, "obtener_hsm", lambda: e.hsm)
    e.body = dict(BODY)
    e.body["encryptedPinBlock"], _ = e.hsm.construir_pin_block(
        "7392", BODY["numeroTarjeta"]
    )
    offset, pvk = e.hsm.generar_offset(
        e.body["encryptedPinBlock"], "TEST-KEY-01", BODY["numeroTarjeta"]
    )
    e.pin = {
        "estado_pin": "Activo",
        "intentos_fallidos": 0,
        "tiene_pin_asignado": True,
        "pin_offset": offset,
        "referencia_clave_pvk": pvk,
    }
    e.tarjeta = {
        "estado_tarjeta": "Activa",
        "pin_asignado": True,
        "fecha_expiracion": date.today() + timedelta(days=30),
        "nombres_titular": "Titular",
        "apellidos_titular": "Prueba",
        "hash_numero_tarjeta": hash_pan(BODY["numeroTarjeta"]),
    }
    monkeypatch.setattr(
        repository,
        "obtener_atm",
        MagicMock(
            return_value={
                "id_atm": 10,
                "id_canal": 4,
                "tipo_terminal": "ATM",
                "estado_atm": "A",
                "estado_canal": "A",
                "requiere_tarjeta": True,
                "requiere_pin": True,
                "requiere_terminal": True,
            }
        ),
    )
    monkeypatch.setattr(
        tarjetas_repository, "obtener_id_tarjeta_por_hash", MagicMock(return_value=301)
    )
    monkeypatch.setattr(
        repository, "obtener_tarjeta", MagicMock(return_value=e.tarjeta)
    )
    monkeypatch.setattr(
        repository,
        "obtener_pin_para_verificacion",
        MagicMock(side_effect=lambda *a: dict(e.pin)),
    )
    monkeypatch.setattr(
        tarjetas_repository,
        "obtener_pan_ficticio",
        MagicMock(return_value=e.hsm.cifrar_pan(BODY["numeroTarjeta"], 301)),
    )
    monkeypatch.setattr(
        repository,
        "obtener_cuentas_autorizadas",
        MagicMock(
            return_value=[
                {
                    "id_cuenta": 77,
                    "numero_cuenta": "0000001234",
                    "tipo_cuenta": "Ahorro",
                },
            ]
        ),
    )

    def guardar(*, conn, id_tarjeta, pin_correcto):
        e.pin["intentos_fallidos"] = (
            0 if pin_correcto else e.pin["intentos_fallidos"] + 1
        )
        if e.pin["intentos_fallidos"] >= 3:
            e.pin["estado_pin"] = "Bloqueado"
        return dict(e.pin)

    e.guardar = MagicMock(side_effect=guardar)
    monkeypatch.setattr(repository, "guardar_resultado_pin", e.guardar)
    e.bloquear = MagicMock(
        side_effect=lambda *a: e.tarjeta.update(estado_tarjeta="Bloqueada")
    )
    monkeypatch.setattr(repository, "bloquear_tarjeta_por_pin", e.bloquear)
    return e


def test_http_con_servicio_iso4_offset_y_custodia_reales(cadena):
    respuesta = cadena.client.post(
        "/api/v1/atm/auth", json=cadena.body, headers=cadena.headers
    )
    assert respuesta.status_code == 200, respuesta.text
    assert cadena.guardar.call_args.kwargs["pin_correcto"] is True
    assert cadena.pin["intentos_fallidos"] == 0


def test_tres_fallos_bloquean_pin_tarjeta_y_no_permiten_pin_correcto(cadena):
    e = cadena
    incorrecto = dict(e.body)
    incorrecto["encryptedPinBlock"], _ = e.hsm.construir_pin_block(
        "8294", BODY["numeroTarjeta"]
    )
    for esperado in (401, 401, 423):
        assert (
            e.client.post(
                "/api/v1/atm/auth", json=incorrecto, headers=e.headers
            ).status_code
            == esperado
        )
    assert e.pin["intentos_fallidos"] == 3
    assert e.tarjeta["estado_tarjeta"] == "Bloqueada"
    assert e.bloquear.call_args.args[1:4] == (301, 4, 900)
    assert (
        e.client.post("/api/v1/atm/auth", json=e.body, headers=e.headers).status_code
        == 423
    )
    assert e.guardar.call_count == 3


@pytest.mark.parametrize("fallo", ["offset", "contador", "hsm", "clave", "bloque"])
def test_errores_internos_y_bloqueo_inconsistente_no_consumen_intentos(
    cadena, monkeypatch, fallo
):
    e = cadena
    if fallo == "offset":
        e.pin["pin_offset"] = "12"
    elif fallo == "contador":
        e.pin["intentos_fallidos"] = 3
    elif fallo == "hsm":
        monkeypatch.setattr(
            service, "obtener_hsm", MagicMock(side_effect=HsmNoDisponible())
        )
    elif fallo == "clave":
        e.body["keyReference"] = "UNKNOWN"
    else:
        e.body["encryptedPinBlock"] = "0" * 32
    antes = e.pin["intentos_fallidos"]
    respuesta = e.client.post("/api/v1/atm/auth", json=e.body, headers=e.headers)
    assert respuesta.status_code in (409, 422, 423, 503)
    assert "sessionToken" not in respuesta.json()
    e.guardar.assert_not_called()
    assert e.pin["intentos_fallidos"] == antes


def test_fallo_historial_no_desbloquea_pin_y_se_reintenta(cadena):
    e = cadena
    e.pin["intentos_fallidos"] = 3
    e.pin["estado_pin"] = "Bloqueado"
    e.bloquear.side_effect = SQLAlchemyError("falla simulada")
    assert (
        e.client.post("/api/v1/atm/auth", json=e.body, headers=e.headers).status_code
        == 503
    )
    assert e.pin["intentos_fallidos"] == 3
    assert e.tarjeta["estado_tarjeta"] == "Activa"
    e.bloquear.side_effect = lambda *a: e.tarjeta.update(estado_tarjeta="Bloqueada")
    assert (
        e.client.post("/api/v1/atm/auth", json=e.body, headers=e.headers).status_code
        == 423
    )
    assert e.tarjeta["estado_tarjeta"] == "Bloqueada"


@pytest.mark.parametrize("estado", [None, "Activa", "Bloqueada", "Cancelada"])
def test_sql_bloqueo_idempotente_parametrizado_y_canal_atm(estado):
    conn = MagicMock()
    conn.execute.return_value.scalar_one_or_none.return_value = estado
    repository.bloquear_tarjeta_por_pin(conn, 301, 4, 900, "127.0.0.1")
    assert conn.execute.call_count == (3 if estado == "Activa" else 1)
    assert "UPDLOCK" in str(conn.execute.call_args_list[0].args[0])
    if estado == "Activa":
        sql, params = conn.execute.call_args.args
        assert "TarjetaHis" in str(sql)
        assert params == {"id": 301, "canal": 4, "usuario": 900, "ip": "127.0.0.1"}
        assert BODY["numeroTarjeta"] not in str(params)


@pytest.mark.parametrize("tipo", ["Debito", "Credito"])
def test_tar01_tar04_atm01_comparten_pan_y_pin_generado(api, monkeypatch, tipo, caplog):
    """Solicitud, aprobación (PIN generado por el HSM), generación y ATM-01 con HTTP
    real; bases exclusivamente simuladas.

    Débito: el PIN es temporal y ATM-01 abre la sesión restringida, sin cuentas.
    Crédito: con 3 días laborables desde la emisión, ATM-01 la activa y opera.
    """
    e = api
    memoria = instalar(monkeypatch)
    monkeypatch.setattr(service, "validar_acceso_atm", ACCESO_REAL)
    monkeypatch.setattr(service, "get_engine", e.get_engine)
    monkeypatch.setattr(service, "obtener_hsm", lambda: HSM)
    fila = {**FILA, "tipo_tarjeta": tipo}
    cooperativa, seguridad = MagicMock(), MagicMock()
    capturado = {}

    def insertar(_conn, datos):
        capturado.update(datos)
        return 301

    def actualizar(_c, _i, estado, *, pin_asignado=False, **_kw):
        fila.update(estado_actual=estado)
        if pin_asignado:
            fila.update(pin_asignado=True)

    monkeypatch.setattr(tarjetas_service, "_generar_pan", lambda _bin: PAN)
    monkeypatch.setattr(tarjetas_repository, "obtener_cuenta", lambda *_: CUENTA)
    monkeypatch.setattr(
        tarjetas_repository,
        "obtener_producto",
        lambda *_: {"tipo_producto": "Tarjeta", "estado": "A"},
    )
    monkeypatch.setattr(
        tarjetas_repository, "obtener_subproducto_con_bin", lambda *_: SUBPRODUCTO
    )
    monkeypatch.setattr(tarjetas_repository, "insertar_tarjeta", insertar)
    monkeypatch.setattr(tarjetas_repository, "insertar_historial", MagicMock())
    monkeypatch.setattr(
        tarjetas_repository, "obtener_tarjeta", lambda *_, **kw: dict(fila)
    )
    monkeypatch.setattr(tarjetas_repository, "existe_transicion", lambda *_: True)
    monkeypatch.setattr(tarjetas_repository, "actualizar_estado", actualizar)
    monkeypatch.setattr(tarjetas_repository, "dias_laborables_desde", lambda *_: 3)

    tarjeta = tarjetas_service.crear_tarjeta(
        cooperativa, seguridad, TarjetaCreate.model_validate(PAYLOAD), 900, None
    )
    assert tarjeta.estado_actual == "Solicitada"
    assert capturado["hash_pan"] == hash_pan(PAN)
    cifrado, referencia_pan = memoria.pans[301]
    assert HSM.descifrar_pan(cifrado, referencia_pan, 301) == PAN
    assert PAN.encode() not in cifrado

    # ATM ve el mismo hash/estado que han escrito los productores.
    def leer_tarjeta(*_):
        return {
            "estado_tarjeta": fila["estado_actual"],
            "tipo_tarjeta": fila["tipo_tarjeta"],
            "pin_asignado": fila["pin_asignado"],
            "fecha_emision": fila["fecha_emision"],
            "fecha_expiracion": fila["fecha_expiracion"],
            "nombres_titular": "Titular",
            "apellidos_titular": "Prueba",
            "hash_numero_tarjeta": capturado["hash_pan"],
        }

    def resolver(_conn, digest):
        assert digest == capturado["hash_pan"]
        return 301

    def leer_pin(*_):
        pin = memoria.pin(301)
        return {
            "estado_pin": pin["estado"],
            "intentos_fallidos": 0,
            "tiene_pin_asignado": True,
            "pin_offset": pin["offset"],
            "referencia_clave_pvk": pin["pvk"],
            "requiere_cambio": pin["requiere_cambio"],
        }

    def activar(_conn, id_tarjeta, id_canal, usuario, _ip):
        assert (id_tarjeta, id_canal, usuario) == (301, 4, 900)
        fila.update(estado_actual="Activa")

    monkeypatch.setattr(tarjetas_repository, "obtener_id_tarjeta_por_hash", resolver)
    monkeypatch.setattr(repository, "obtener_tarjeta", leer_tarjeta)
    monkeypatch.setattr(repository, "obtener_pin_para_verificacion", leer_pin)
    monkeypatch.setattr(repository, "activar_tarjeta_credito", activar)
    monkeypatch.setattr(
        repository,
        "obtener_atm",
        lambda *_: {
            "id_atm": 10,
            "id_canal": 4,
            "tipo_terminal": "ATM",
            "estado_atm": "A",
            "estado_canal": "A",
            "requiere_tarjeta": True,
            "requiere_pin": True,
            "requiere_terminal": True,
        },
    )
    monkeypatch.setattr(
        repository,
        "obtener_cuentas_autorizadas",
        lambda *_: [
            {"id_cuenta": 77, "numero_cuenta": "000001234", "tipo_cuenta": "Ahorro"}
        ],
    )
    guardar = MagicMock(return_value={"estado_pin": "Activo", "intentos_fallidos": 0})
    monkeypatch.setattr(repository, "guardar_resultado_pin", guardar)

    body = {**BODY, "numeroTarjeta": PAN}
    # Solicitada: sin PIN, no opera.
    assert (
        e.client.post("/api/v1/atm/auth", json=body, headers=e.headers).status_code
        == 409
    )

    for destino in ("Aprobada", "Generada"):
        tarjetas_service.cambiar_estado(
            cooperativa,
            seguridad,
            301,
            TarjetaEstadoUpdate(estado=destino, motivo="Prueba local"),
            900,
            None,
        )
    assert fila["estado_actual"] == "Generada" and fila["pin_asignado"]
    assert memoria.pin(301)["requiere_cambio"] is (tipo == "Debito")

    # El PIN nadie lo conoce: solo la prueba lo reconstruye para simular al cliente.
    pin = pin_generado(memoria)
    bloque, ref = HSM.construir_pin_block(pin, PAN)
    body.update(encryptedPinBlock=bloque, keyReference=ref)
    respuesta = e.client.post("/api/v1/atm/auth", json=body, headers=e.headers)

    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    claims = jwt.decode(
        cuerpo["sessionToken"],
        e.publica,
        algorithms=["RS256"],
        issuer="urn:test:atm",
        audience="urn:test:operations",
    )
    assert claims["idTarjeta"] == 301 and claims["idATM"] == 10
    assert claims["exp"] - claims["iat"] == 300
    guardar.assert_called_once()
    if tipo == "Debito":
        # Sesión restringida: solo cambio de PIN; la tarjeta sigue Generada.
        assert cuerpo["cambioPinRequerido"] is True and cuerpo["cuentas"] == []
        assert claims["cambioPinRequerido"] is True and claims["cuentas"] == []
        assert fila["estado_actual"] == "Generada"
    else:
        assert cuerpo["cambioPinRequerido"] is False
        assert claims["cambioPinRequerido"] is False and claims["cuentas"] == [77]
        assert fila["estado_actual"] == "Activa"
    for secreto in (PAN, pin, bloque, e.secret):
        assert secreto not in respuesta.text and secreto not in caplog.text
