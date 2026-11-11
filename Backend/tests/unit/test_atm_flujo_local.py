"""Flujo de la aplicación completa, con HSM real del simulador y SQL simulado.

No usa .env, credenciales reales, servidores HTTP ni bases de datos. TestClient
simula HTTPS en ASGI: no demuestra una negociación TLS ni persistencia SQL.
"""

import hashlib
import json
import logging
import secrets
import socket
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.config import settings as configuracion
from app.core.security import hsm as modulo_hsm
from app.modules.atm import repository, router, service, session, terminal_auth
from app.modules.tarjetas import repository as tarjetas_repository
from app.modules.tarjetas.identificacion import hash_pan
from tests.pin_version import FECHA_PIN

PAN_FICTICIO = "5000001234567896"
PIN_LAB = "7392"
PIN_INCORRECTO = "8294"
EMISOR = "urn:laboratorio:atm"
AUDIENCIA = "urn:laboratorio:operaciones"
ENDPOINT = "/api/v1/atm/auth"


@pytest.fixture(autouse=True)
def sin_conexiones_reales(monkeypatch):
    conectar = socket.socket.connect

    def prohibido(*_args, **_kwargs):
        raise AssertionError("Esta prueba prohíbe conexiones SQL o externas")

    def solo_loopback(sock, direccion):
        # Windows implementa socketpair de asyncio mediante loopback local.
        if isinstance(direccion, tuple) and direccion[0] in {"127.0.0.1", "::1"}:
            return conectar(sock, direccion)
        return prohibido()

    monkeypatch.setattr(socket.socket, "connect", solo_loopback)
    monkeypatch.setattr(socket, "getaddrinfo", prohibido)
    monkeypatch.setattr("pyodbc.connect", prohibido)
    monkeypatch.setattr("sqlalchemy.create_engine", prohibido)
    monkeypatch.setattr("app.core.database.db.create_engine", prohibido)


@dataclass(repr=False)
class Laboratorio:
    client: TestClient
    hsm: modulo_hsm.Hsm
    publica: rsa.RSAPublicKey
    credencial: str
    pin: dict[str, Any]
    tarjeta: dict[str, Any]
    historial: list[dict[str, Any]]
    auditoria: list[Any]
    motor: MagicMock
    guardar: MagicMock
    sensibles: set[str] = field(default_factory=set)

    def autenticar(self, pin: str, cabeceras: dict[str, str] | None = None):
        if cabeceras and (valor := cabeceras.get("X-ATM-Credential")):
            self.sensibles.add(valor)
            if "." in valor:
                self.sensibles.add(valor.split(".", 1)[1])
        bloque, referencia = self.hsm.construir_pin_block(pin, PAN_FICTICIO)
        self.sensibles.add(bloque)
        respuesta = self.client.post(
            ENDPOINT,
            headers={"X-ATM-Credential": self.credencial}
            if cabeceras is None
            else cabeceras,
            json={
                "codigoATM": "ATM00001",
                "numeroTarjeta": PAN_FICTICIO,
                "encryptedPinBlock": bloque,
                "keyReference": referencia,
            },
        )
        token = respuesta.json().get("sessionToken")
        if token:
            self.sensibles.add(token)
        return respuesta

    def verificar_token(self, token):
        return jwt.decode(
            token, self.publica, algorithms=["RS256"], issuer=EMISOR, audience=AUDIENCIA
        )

    def verificar_logs(self, caplog):
        # Incluye los eventos producidos por el middleware real de auditoría;
        # únicamente su escritura SQL fue reemplazada por la lista en memoria.
        observado = caplog.text + repr(self.auditoria) + repr(self.historial)
        assert not any(valor in observado for valor in self.sensibles)


@pytest.fixture
def laboratorio(tmp_path, monkeypatch, eventos_auditados, caplog):
    caplog.set_level(logging.INFO)
    clave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = clave.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    identificador, secreto = secrets.token_urlsafe(12), secrets.token_urlsafe(32)
    credencial = identificador + "." + secreto
    ahora = datetime.now(UTC)
    registro = tmp_path / "terminales-laboratorio.json"
    registro.write_text(
        json.dumps(
            {
                identificador: {
                    "codigoATM": "ATM00001",
                    "sha256": hashlib.sha256(secreto.encode()).hexdigest(),
                    "enabled": True,
                    "notBefore": (ahora - timedelta(minutes=1)).isoformat(),
                    "expiresAt": (ahora + timedelta(minutes=30)).isoformat(),
                    "auditUserId": 900,
                }
            }
        ),
        encoding="utf-8",
    )
    claves = [secrets.token_hex(32), secrets.token_hex(24), secrets.token_hex(32)]
    ajustes = configuracion.Settings.model_construct(
        app_env="development",
        atm_terminal_credentials_file=str(registro),
        atm_jwt_private_key_pem=SecretStr(pem),
        atm_jwt_issuer=EMISOR,
        atm_jwt_audience=AUDIENCIA,
        hsm_sim_clave_pan=SecretStr(claves[0]),
        hsm_sim_clave_pvk=SecretStr(claves[1]),
        hsm_sim_claves_pin_block={"LAB-PIN-01": SecretStr(claves[2])},
        hsm_sim_referencia_pin_block="LAB-PIN-01",
    )
    for modulo in (configuracion, modulo_hsm, terminal_auth, session):
        monkeypatch.setattr(modulo, "get_settings", lambda: ajustes)
    # No se reemplaza obtener_hsm, verificar_pin ni el servicio de autenticación.
    hsm = modulo_hsm.obtener_hsm()
    bloque, referencia = hsm.construir_pin_block(PIN_LAB, PAN_FICTICIO)
    offset, pvk = hsm.generar_offset(bloque, referencia, PAN_FICTICIO)
    custodia = hsm.cifrar_pan(PAN_FICTICIO, 301)
    estado_pin = {
        "estado_pin": "Activo",
        "tiene_pin_asignado": True,
        "intentos_fallidos": 0,
        "fecha_asignacion": FECHA_PIN,
        "pin_offset": offset,
        "referencia_clave_pvk": pvk,
    }
    tarjeta = {
        "estado_tarjeta": "Activa",
        "pin_asignado": True,
        "fecha_expiracion": date.today() + timedelta(days=30),
        "nombres_titular": "Persona",
        "apellidos_titular": "Ficticia",
        "hash_numero_tarjeta": hash_pan(PAN_FICTICIO),
    }
    motor = MagicMock()
    monkeypatch.setattr(router, "get_engine", motor)
    monkeypatch.setattr(service, "get_engine", motor)
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

    def resolver(_conn, digest):
        assert isinstance(digest, bytes)
        return 301 if digest == tarjeta["hash_numero_tarjeta"] else None

    monkeypatch.setattr(tarjetas_repository, "obtener_id_tarjeta_por_hash", resolver)
    monkeypatch.setattr(
        tarjetas_repository, "obtener_pan_ficticio", lambda *_: custodia
    )
    monkeypatch.setattr(repository, "obtener_tarjeta", lambda *_: dict(tarjeta))
    monkeypatch.setattr(
        repository, "obtener_pin_para_verificacion", lambda *_: dict(estado_pin)
    )
    monkeypatch.setattr(
        repository,
        "obtener_cuentas_autorizadas",
        lambda *_: [
            {
                "id_cuenta": 77,
                "numero_cuenta": "0000001234",
                "tipo_cuenta": "Ahorro",
            }
        ],
    )

    def actualizar(*, conn, id_tarjeta, pin_correcto):
        assert id_tarjeta == 301
        estado_pin["intentos_fallidos"] = (
            0 if pin_correcto else estado_pin["intentos_fallidos"] + 1
        )
        if estado_pin["intentos_fallidos"] >= 3:
            estado_pin["estado_pin"] = "Bloqueado"
        return dict(estado_pin)

    guardar = MagicMock(side_effect=actualizar)
    monkeypatch.setattr(repository, "guardar_resultado_pin", guardar)
    historial = []

    def bloquear(_conn, id_tarjeta, canal, usuario, _ip):
        if tarjeta["estado_tarjeta"] == "Activa":
            tarjeta["estado_tarjeta"] = "Bloqueada"
            historial.append(
                {
                    "idTarjeta": id_tarjeta,
                    "canal": canal,
                    "usuario": usuario,
                    "evento": "Bloqueo",
                }
            )

    monkeypatch.setattr(repository, "bloquear_tarjeta_por_pin", bloquear)
    from app.main import app

    caplog.set_level(logging.DEBUG)
    with TestClient(app, base_url="https://testserver") as client:
        entorno = Laboratorio(
            client,
            hsm,
            clave.public_key(),
            credencial,
            estado_pin,
            tarjeta,
            historial,
            eventos_auditados,
            motor,
            guardar,
        )
        entorno.sensibles.update(
            [
                PAN_FICTICIO,
                PIN_LAB,
                PIN_INCORRECTO,
                credencial,
                secreto,
                pem,
                bloque,
                *claves,
            ]
        )
        yield entorno
        entorno.verificar_logs(caplog)


def test_tarjeta_activa_devuelve_cuentas_y_rs256_300_segundos(laboratorio):
    respuesta = laboratorio.autenticar(PIN_LAB)
    assert respuesta.status_code == 200
    datos = respuesta.json()
    claims = laboratorio.verificar_token(datos["sessionToken"])
    assert jwt.get_unverified_header(datos["sessionToken"])["alg"] == "RS256"
    assert claims["exp"] - claims["iat"] == datos["expiresIn"] == 300
    assert claims["idATM"] == 10 and claims["idTarjeta"] == 301
    assert claims["cuentas"] == [77] and claims["scope"] == "atm"
    assert claims["jti"]
    assert datos["cuentas"] == [
        {
            "idCuenta": 77,
            "numeroCuentaEnmascarado": "******1234",
            "tipoCuenta": "Ahorro",
        }
    ]
    assert respuesta.headers["cache-control"] == "no-store"
    assert laboratorio.pin["intentos_fallidos"] == 0
    assert PAN_FICTICIO not in json.dumps(claims)


def test_mismo_jwt_valido_a_299_y_caducado_a_300(laboratorio, monkeypatch):
    respuesta = laboratorio.autenticar(PIN_LAB)
    assert respuesta.status_code == 200
    token = respuesta.json()["sessionToken"]
    claims = laboratorio.verificar_token(token)
    instante = claims["iat"] + 299

    class Reloj(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.fromtimestamp(instante, tz=tz)

    # Solo se adelanta el reloj del verificador. Firma y token permanecen intactos.
    monkeypatch.setattr(jwt.api_jwt, "datetime", Reloj)
    laboratorio.verificar_token(token)
    instante += 1
    with pytest.raises(jwt.ExpiredSignatureError):
        laboratorio.verificar_token(token)


def test_pin_incorrecto_incrementa_y_bloquea_al_tercer_fallo(laboratorio):
    for contador, status in enumerate((401, 401, 423), start=1):
        respuesta = laboratorio.autenticar(PIN_INCORRECTO)
        assert respuesta.status_code == status
        assert respuesta.json()["code"] == (
            "PIN_INCORRECTO" if contador < 3 else "PIN_BLOQUEADO"
        )
        assert laboratorio.pin["intentos_fallidos"] == contador
        assert "sessionToken" not in respuesta.json()
    assert laboratorio.tarjeta["estado_tarjeta"] == "Bloqueada"
    assert laboratorio.pin["estado_pin"] == "Bloqueado"
    assert len(laboratorio.historial) == 1
    assert laboratorio.autenticar(PIN_LAB).status_code == 423
    assert laboratorio.pin["intentos_fallidos"] == 3
    assert laboratorio.guardar.call_count == 3


def test_pin_correcto_reinicia_intentos_anteriores(laboratorio):
    for _ in range(2):
        assert laboratorio.autenticar(PIN_INCORRECTO).status_code == 401
    assert laboratorio.pin["intentos_fallidos"] == 2
    assert laboratorio.autenticar(PIN_LAB).status_code == 200
    assert laboratorio.pin["intentos_fallidos"] == 0


@pytest.mark.parametrize("caso", ["ausente", "formato_invalido", "secreto_incorrecto"])
def test_terminal_no_autorizado_es_401_antes_de_procesar_pin(laboratorio, caso):
    if caso == "ausente":
        headers = {}
    elif caso == "formato_invalido":
        headers = {"X-ATM-Credential": "invalid"}
    else:
        identificador = laboratorio.credencial.split(".")[0]
        headers = {"X-ATM-Credential": identificador + "." + secrets.token_urlsafe(32)}
    respuesta = laboratorio.autenticar(PIN_LAB, headers)
    assert respuesta.status_code == 401
    assert respuesta.json()["code"] == "TERMINAL_NO_AUTORIZADO"
    assert "sessionToken" not in respuesta.json()
    laboratorio.motor.assert_not_called()
    laboratorio.guardar.assert_not_called()
    assert laboratorio.pin["intentos_fallidos"] == 0
    assert laboratorio.auditoria[-1].accion == "ACCESO_DENEGADO"
