"""JWT RS256 con claves efímeras en memoria y sin conexiones externas."""

import base64
import json
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, cast
from unittest.mock import MagicMock

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from fastapi import HTTPException
from fastapi.routing import APIRoute
from jwt.exceptions import (
    ExpiredSignatureError,
    InvalidAudienceError,
    InvalidIssuerError,
    InvalidSignatureError,
)
from pydantic import SecretStr

from app.core.config.settings import Settings
from app.modules.atm import router, session
from app.modules.atm.schemas import CuentaATM
from app.modules.atm.service import AccesoATMValidado

ISSUER = "urn:pruebas:emisor-atm"
AUDIENCE = "urn:pruebas:operaciones-atm"


@pytest.fixture(autouse=True)
def sin_conexiones_reales(monkeypatch):
    def prohibido(*args, **kwargs):
        raise AssertionError("Las pruebas JWT no pueden abrir conexiones reales")

    monkeypatch.setattr("pyodbc.connect", prohibido)
    monkeypatch.setattr("sqlalchemy.create_engine", prohibido)
    monkeypatch.setattr("app.core.database.db.create_engine", prohibido)


def pem_privado(clave) -> str:
    return clave.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()


@pytest.fixture(scope="module")
def clave_rsa():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def configuracion(monkeypatch, clave_rsa):
    # model_construct no consulta variables de entorno, .env ni Key Vault.
    settings = Settings.model_construct(
        atm_jwt_private_key_pem=SecretStr(pem_privado(clave_rsa)),
        atm_jwt_issuer=ISSUER,
        atm_jwt_audience=AUDIENCE,
    )
    monkeypatch.setattr(session, "get_settings", lambda: settings)
    return settings


@pytest.fixture
def acceso():
    return AccesoATMValidado(
        id_atm=7,
        id_tarjeta=301,
        titular="Cliente de prueba",
        cuentas=[
            CuentaATM(
                id_cuenta=501,
                numero_cuenta_enmascarado="********0501",
                tipo_cuenta="Ahorro",
            ),
            CuentaATM(
                id_cuenta=502,
                numero_cuenta_enmascarado="********0502",
                tipo_cuenta="Corriente",
            ),
        ],
        pin_version="2026-11-01T10:00:00.000000",
    )


def verificar(token, clave_rsa):
    return jwt.decode(
        token,
        clave_rsa.public_key(),
        algorithms=["RS256"],
        issuer=ISSUER,
        audience=AUDIENCE,
        options={"require": ["iss", "aud", "iat", "exp", "jti"]},
    )


def test_rs256_firma_verificable_claims_y_vigencia(configuracion, clave_rsa, acceso):
    inicio = int(datetime.now(UTC).timestamp())
    respuesta = session.emitir_sesion_atm(acceso)
    fin = int(datetime.now(UTC).timestamp())
    claims = verificar(respuesta.session_token, clave_rsa)
    assert jwt.get_unverified_header(respuesta.session_token) == {
        "alg": "RS256",
        "typ": "JWT",
    }
    assert set(claims) == {
        "iss",
        "aud",
        "iat",
        "exp",
        "jti",
        "scope",
        "idATM",
        "idTarjeta",
        "cuentas",
        "cambioPinRequerido",
        "pinVersion",
    }
    assert claims["cambioPinRequerido"] is False
    assert claims["iss"] == ISSUER
    assert claims["aud"] == AUDIENCE
    assert inicio <= claims["iat"] <= fin
    assert claims["exp"] - claims["iat"] == 300
    assert claims["scope"] == "atm"
    assert claims["idATM"] == 7
    assert claims["idTarjeta"] == 301
    assert claims["cuentas"] == [501, 502]
    assert uuid.UUID(claims["jti"]).version == 4
    assert respuesta.expires_in == 300
    assert respuesta.titular == acceso.titular
    assert respuesta.cuentas == acceso.cuentas


def test_cada_sesion_tiene_jti_unico(configuracion, clave_rsa, acceso):
    primero = verificar(session.emitir_sesion_atm(acceso).session_token, clave_rsa)
    segundo = verificar(session.emitir_sesion_atm(acceso).session_token, clave_rsa)
    assert primero["jti"] != segundo["jti"]


def test_no_serializa_datos_personales_en_jwt_ni_registra_token(
    configuracion, clave_rsa, acceso, caplog
):
    respuesta = session.emitir_sesion_atm(acceso)
    claims = verificar(respuesta.session_token, clave_rsa)
    texto = json.dumps(claims)
    assert acceso.titular not in texto
    assert acceso.cuentas[0].numero_cuenta_enmascarado not in texto
    assert "numeroTarjeta" not in texto
    assert "encryptedPinBlock" not in texto
    assert "pin" not in claims
    assert "PRIVATE KEY" not in texto
    assert (
        configuracion.atm_jwt_private_key_pem.get_secret_value()
        not in texto + caplog.text
    )
    assert respuesta.session_token not in caplog.text


@pytest.mark.parametrize("fallo", ["payload", "firma"])
def test_token_alterado_rechazado(configuracion, clave_rsa, acceso, fallo):
    token = session.emitir_sesion_atm(acceso).session_token
    partes = token.split(".")
    if fallo == "payload":
        claims = verificar(token, clave_rsa)
        claims["cuentas"] = [999]
        partes[1] = (
            base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
        )
    else:
        firma = bytearray(
            base64.urlsafe_b64decode(partes[2] + "=" * (-len(partes[2]) % 4))
        )
        firma[0] ^= 1
        partes[2] = base64.urlsafe_b64encode(firma).rstrip(b"=").decode()
    with pytest.raises(InvalidSignatureError):
        verificar(".".join(partes), clave_rsa)


def test_firma_con_otra_clave_no_verifica(configuracion, acceso):
    otra = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = session.emitir_sesion_atm(acceso).session_token
    with pytest.raises(InvalidSignatureError):
        verificar(token, otra)


def test_expiracion_real_sin_mockear_firma(configuracion, clave_rsa, acceso):
    claims = verificar(session.emitir_sesion_atm(acceso).session_token, clave_rsa)
    claims["iat"] = int(datetime.now(UTC).timestamp()) - 301
    claims["exp"] = claims["iat"] + 300
    vencido = jwt.encode(claims, clave_rsa, algorithm="RS256")
    with pytest.raises(ExpiredSignatureError):
        verificar(vencido, clave_rsa)


@pytest.mark.parametrize(
    "campo,error", [("iss", InvalidIssuerError), ("aud", InvalidAudienceError)]
)
def test_emisor_y_audiencia_se_verifican(
    configuracion, clave_rsa, acceso, campo, error
):
    claims = verificar(session.emitir_sesion_atm(acceso).session_token, clave_rsa)
    claims[campo] = "urn:otro-servicio"
    otro = jwt.encode(claims, clave_rsa, algorithm="RS256")
    with pytest.raises(error):
        verificar(otro, clave_rsa)


@pytest.mark.parametrize(
    "campo", ["atm_jwt_private_key_pem", "atm_jwt_issuer", "atm_jwt_audience"]
)
@pytest.mark.parametrize("valor", ["", " "])
def test_falta_configuracion_rechaza_sin_sesion(
    configuracion, acceso, campo, valor, caplog
):
    setattr(configuracion, campo, SecretStr(valor) if campo.endswith("pem") else valor)
    with pytest.raises(HTTPException) as error:
        session.emitir_sesion_atm(acceso)
    assert error.value.status_code == 503
    assert cast(dict[str, Any], error.value.detail) == {
        "code": "SESION_ATM_NO_DISPONIBLE",
        "message": "No se pudo emitir la sesión ATM.",
    }
    assert caplog.text == ""


@pytest.mark.parametrize("tipo", ["invalida", "publica", "ec", "rsa_corta", "cifrada"])
def test_clave_inadecuada_falla_sin_filtrar_detalles(
    configuracion, clave_rsa, acceso, tipo, caplog
):
    if tipo == "invalida":
        pem = "contenido privado ficticio invalido"
    elif tipo == "publica":
        pem = (
            clave_rsa.public_key()
            .public_bytes(
                serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
            .decode()
        )
    elif tipo == "ec":
        pem = pem_privado(ec.generate_private_key(ec.SECP256R1()))
    elif tipo == "rsa_corta":
        pem = pem_privado(
            rsa.generate_private_key(public_exponent=65537, key_size=1024)
        )
    else:
        pem = clave_rsa.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.BestAvailableEncryption(b"solo-pruebas-efimeras"),
        ).decode()
    configuracion.atm_jwt_private_key_pem = SecretStr(pem)
    with pytest.raises(HTTPException) as error:
        session.emitir_sesion_atm(acceso)
    assert error.value.status_code == 503
    assert pem not in str(error.value.detail) + caplog.text


def test_fallo_del_firmante_no_genera_respaldo(
    configuracion, acceso, monkeypatch, caplog
):
    firmar = MagicMock(side_effect=jwt.exceptions.InvalidKeyError("detalle privado"))
    monkeypatch.setattr(session.jwt, "encode", firmar)
    with pytest.raises(HTTPException) as error:
        session.emitir_sesion_atm(acceso)
    assert error.value.status_code == 503
    assert "detalle privado" not in str(error.value.detail) + caplog.text
    firmar.assert_called_once()


@pytest.mark.parametrize(
    "fallo", ["sin_cuentas", "terminal", "tarjeta", "bool", "duplicadas"]
)
def test_contexto_invalido_no_emite(configuracion, acceso, fallo):
    if fallo == "sin_cuentas":
        acceso = replace(acceso, cuentas=[])
    elif fallo == "terminal":
        acceso = replace(acceso, id_atm=0)
    elif fallo == "tarjeta":
        acceso = replace(acceso, id_tarjeta=-1)
    elif fallo == "bool":
        acceso = replace(acceso, id_atm=True)
    else:
        acceso = replace(acceso, cuentas=[acceso.cuentas[0], acceso.cuentas[0]])
    with pytest.raises(HTTPException) as error:
        session.emitir_sesion_atm(acceso)
    assert error.value.status_code == 503


def test_endpoint_conserva_operacion_atm01():
    assert cast(APIRoute, router.router.routes[0]).operation_id == "ATM01"


# A-05: sesión restringida por PIN temporal


def test_sesion_restringida_sin_cuentas_y_con_claim(configuracion, clave_rsa, acceso):
    restringida = replace(acceso, cuentas=[], cambio_pin_requerido=True)

    respuesta = session.emitir_sesion_atm(restringida)

    assert respuesta.cambio_pin_requerido is True and respuesta.cuentas == []
    claims = verificar(respuesta.session_token, clave_rsa)
    assert claims["cambioPinRequerido"] is True and claims["cuentas"] == []
    sesion = session.validar_jwt_atm(respuesta.session_token)
    assert sesion.cambio_pin_requerido is True and sesion.cuentas == ()


@pytest.mark.parametrize(
    "inconsistente",
    [
        {"cambio_pin_requerido": True},  # restringida con cuentas
        {"cambio_pin_requerido": False, "cuentas": []},  # normal sin cuentas
    ],
)
def test_sesion_inconsistente_no_se_emite(configuracion, acceso, inconsistente):
    with pytest.raises(HTTPException) as error:
        session.emitir_sesion_atm(replace(acceso, **inconsistente))
    assert error.value.status_code == 503


@pytest.mark.parametrize(
    "claims",
    [
        {"cambioPinRequerido": True},  # restringida con cuentas
        {"cambioPinRequerido": False, "cuentas": []},
        {"cambioPinRequerido": "false"},
        {"cambioPinRequerido": None},
    ],
)
def test_jwt_con_claim_de_cambio_inconsistente_es_invalido(
    configuracion, clave_rsa, acceso, claims
):
    original = verificar(session.emitir_sesion_atm(acceso).session_token, clave_rsa)
    token = jwt.encode({**original, **claims}, clave_rsa, algorithm="RS256")

    with pytest.raises(HTTPException) as error:
        session.validar_jwt_atm(token)
    assert error.value.status_code == 401


def test_jwt_sin_claim_de_cambio_es_invalido(configuracion, clave_rsa, acceso):
    original = verificar(session.emitir_sesion_atm(acceso).session_token, clave_rsa)
    original.pop("cambioPinRequerido")
    token = jwt.encode(original, clave_rsa, algorithm="RS256")

    with pytest.raises(HTTPException) as error:
        session.validar_jwt_atm(token)
    assert error.value.status_code == 401


def test_sesion_operativa_rechaza_la_restringida(configuracion, acceso):
    respuesta = session.emitir_sesion_atm(
        replace(acceso, cuentas=[], cambio_pin_requerido=True)
    )
    restringida = session.validar_jwt_atm(respuesta.session_token)

    with pytest.raises(HTTPException) as error:
        session.require_sesion_operativa(restringida)
    assert error.value.status_code == 403
    assert cast(dict[str, Any], error.value.detail)["code"] == "PIN_CAMBIO_REQUERIDO"

    normal = session.validar_jwt_atm(session.emitir_sesion_atm(acceso).session_token)
    assert session.require_sesion_operativa(normal) is normal
