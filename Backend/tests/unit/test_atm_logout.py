"""JWT/RSA y HTTP reales; SQL simulado con transacciones serializadas en memoria."""

import copy
import logging
import secrets
import socket
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime
from threading import RLock
from types import SimpleNamespace
from unittest.mock import MagicMock

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.exc import SQLAlchemyError

from app.core.config.settings import Settings
from app.modules.atm import router, session
from app.modules.atm.schemas import CuentaATM
from app.modules.atm.service import AccesoATMValidado

RUTA = "/api/v1/atm/logout"


@pytest.fixture(autouse=True)
def sin_conexiones(monkeypatch):
    original = socket.socket.connect

    def prohibido(*a, **kw):
        raise AssertionError("SQL/red externa prohibidos")

    def local(sock, address):
        if isinstance(address, tuple) and address[0] in {"127.0.0.1", "::1"}:
            return original(sock, address)
        return prohibido()

    monkeypatch.setattr(socket.socket, "connect", local)
    monkeypatch.setattr(socket, "getaddrinfo", prohibido)
    monkeypatch.setattr("pyodbc.connect", prohibido)
    monkeypatch.setattr("sqlalchemy.create_engine", prohibido)
    monkeypatch.setattr("app.core.database.db.create_engine", prohibido)


class Almacen:
    """Doble SQL: no demuestra que Azure SQL aplique los locks del texto enviado."""

    def __init__(self):
        self.lock = RLock()
        self.rows = {}
        self.calls = []
        self.fallo = None
        self.detalle = "error SQL simulado"

    def execute(self, statement, params):
        with self.lock:
            sql = str(statement).strip()
            self.calls.append((sql, dict(params)))
            operacion = "leer" if sql.startswith("SELECT") else "insertar"
            if self.fallo == operacion:
                raise SQLAlchemyError(self.detalle)
            if operacion == "leer":
                valor = 1 if params["jti"] in self.rows else None
            else:
                assert sql.startswith("INSERT INTO Seguridad.SesionesATMRevocadas")
                assert params["jti"] not in self.rows
                self.rows[params["jti"]] = dict(params)
                valor = None
            resultado = MagicMock()
            resultado.scalar_one_or_none.return_value = valor
            return resultado

    @contextmanager
    def connect(self):
        yield self

    @contextmanager
    def begin(self):
        with self.lock:
            previo = copy.deepcopy(self.rows)
            try:
                yield self
                if self.fallo == "commit":
                    raise SQLAlchemyError(self.detalle)
            except Exception:
                self.rows = previo
                raise


@pytest.fixture(scope="module")
def clave():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def entorno(monkeypatch, clave):
    e = SimpleNamespace()
    e.clave = clave
    pem = clave.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    e.settings = Settings.model_construct(
        atm_jwt_private_key_pem=SecretStr(pem),
        atm_jwt_issuer="urn:lab:atm",
        atm_jwt_audience="urn:lab:operaciones",
    )
    monkeypatch.setattr(session, "get_settings", lambda: e.settings)
    e.store = Almacen()
    e.engine = MagicMock(
        side_effect=lambda db: (
            e.store if db == "seguridad" else pytest.fail("Base incorrecta")
        )
    )
    monkeypatch.setattr(session, "get_engine", e.engine)
    e.token = session.emitir_sesion_atm(
        AccesoATMValidado(
            10,
            301,
            "Persona ficticia",
            [
                CuentaATM(
                    id_cuenta=77,
                    numero_cuenta_enmascarado="******1234",
                    tipo_cuenta="Ahorro",
                )
            ],
            pin_version="2026-11-01T10:00:00.000000",
        )
    ).session_token
    e.claims = jwt.decode(
        e.token,
        clave.public_key(),
        algorithms=["RS256"],
        issuer=e.settings.atm_jwt_issuer,
        audience=e.settings.atm_jwt_audience,
    )
    e.headers = {"Authorization": "Bearer " + e.token}

    def instancia():
        app = FastAPI()
        app.include_router(router.router, prefix="/api/v1")

        # Consumidor de prueba: no se publica un endpoint financiero nuevo.
        @app.get(
            "/operacion-de-prueba", dependencies=[Depends(session.require_sesion_atm)]
        )
        def operacion():
            return {"ok": True}

        return TestClient(app, base_url="https://testserver")

    e.a, e.b = instancia(), instancia()
    return e


def test_logout_204_repetido_conserva_una_revocacion_y_expiracion(entorno):
    e = entorno
    for client in (e.a, e.b, e.a):
        respuesta = client.post(RUTA, headers=e.headers)
        assert respuesta.status_code == 204
        assert respuesta.content == b""
        assert respuesta.headers["cache-control"] == "no-store"
    assert len(e.store.rows) == 1
    fila = e.store.rows[e.claims["jti"]]
    assert fila["expiracion"] == datetime.fromtimestamp(e.claims["exp"], UTC).replace(
        tzinfo=None
    )
    inserts = [sql for sql, _ in e.store.calls if sql.startswith("INSERT")]
    assert len(inserts) == 1
    assert all(set(params) <= {"jti", "expiracion"} for _, params in e.store.calls)
    assert any("UPDLOCK, HOLDLOCK" in sql for sql, _ in e.store.calls)


@pytest.mark.parametrize(
    "caso",
    [
        "ausente",
        "basico",
        "corrupto",
        "firma",
        "expirado",
        "audiencia",
        "emisor",
        "algoritmo",
        "none",
        "sin_jti",
        "jti",
        "scope",
        "duracion",
        "id_booleano",
        "cuentas",
        "futuro",
        "sin_exp",
    ],
)
def test_tokens_no_validos_401_sin_sql(entorno, caso):
    e = entorno
    datos = dict(e.claims)
    headers = dict(e.headers)
    if caso == "ausente":
        headers = {}
    elif caso == "basico":
        headers = {"Authorization": "Basic invalid"}
    elif caso == "corrupto":
        headers = {"Authorization": "Bearer invalid"}
    else:
        clave_firma = e.clave
        algoritmo = "RS256"
        if caso == "firma":
            clave_firma = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        elif caso == "expirado":
            datos["iat"] -= 301
            datos["exp"] -= 301
        elif caso == "audiencia":
            datos["aud"] = "otra"
        elif caso == "emisor":
            datos["iss"] = "otro"
        elif caso == "algoritmo":
            headers = {
                "Authorization": "Bearer "
                + jwt.encode(datos, secrets.token_bytes(32), algorithm="HS256")
            }
        elif caso == "none":
            headers = {
                "Authorization": "Bearer " + jwt.encode(datos, "", algorithm="none")
            }
        elif caso == "sin_jti":
            del datos["jti"]
        elif caso == "sin_exp":
            del datos["exp"]
        elif caso == "jti":
            datos["jti"] = "no-uuid"
        elif caso == "scope":
            datos["scope"] = "web"
        elif caso == "duracion":
            datos["exp"] += 1
        elif caso == "id_booleano":
            datos["idATM"] = True
        elif caso == "cuentas":
            datos["cuentas"] = []
        elif caso == "futuro":
            datos["iat"] += 30
            datos["exp"] += 30
        if caso not in {"algoritmo", "none"}:
            headers = {
                "Authorization": "Bearer "
                + jwt.encode(datos, clave_firma, algorithm=algoritmo)
            }
    respuesta = e.a.post(RUTA, headers=headers)
    assert respuesta.status_code == 401
    assert respuesta.json()["code"] == "SESION_ATM_INVALIDA"
    assert respuesta.headers["www-authenticate"] == "Bearer"
    e.engine.assert_not_called()


@pytest.mark.parametrize(
    "headers",
    [
        [("Authorization", "Bearer invalid")] * 2,
        {"Authorization": "Bearer " + "x" * 8193},
    ],
)
def test_cabeceras_ambiguas_o_excesivas_401(entorno, headers):
    assert entorno.a.post(RUTA, headers=headers).status_code == 401
    entorno.engine.assert_not_called()


@pytest.mark.parametrize("caso", ["body", "query", "http"])
def test_contrato_sin_body_ni_parametros_y_https(entorno, caso):
    e = entorno
    url = "http://testserver" + RUTA if caso == "http" else RUTA
    if caso == "query":
        url += "?extra=1"
    respuesta = e.a.post(
        url, headers=e.headers, content=b"{}" if caso == "body" else b""
    )
    assert respuesta.status_code == 400
    e.engine.assert_not_called()


def test_revocacion_compartida_entre_instancias_sin_cache(entorno):
    e = entorno
    assert e.b.get("/operacion-de-prueba", headers=e.headers).status_code == 200
    assert e.a.post(RUTA, headers=e.headers).status_code == 204
    assert e.b.get("/operacion-de-prueba", headers=e.headers).status_code == 401
    assert e.b.post(RUTA, headers=e.headers).status_code == 204


def test_token_revocado_y_luego_expirado_es_401_antes_de_sql(entorno, monkeypatch):
    e = entorno
    assert e.a.post(RUTA, headers=e.headers).status_code == 204
    e.engine.reset_mock()

    class Reloj(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.fromtimestamp(e.claims["exp"], tz=tz)

    monkeypatch.setattr(jwt.api_jwt, "datetime", Reloj)
    assert e.b.post(RUTA, headers=e.headers).status_code == 401
    e.engine.assert_not_called()


@pytest.mark.parametrize("fallo", ["leer", "insertar", "commit"])
def test_fallo_almacenamiento_no_devuelve_204_ni_filtra_token(entorno, fallo, caplog):
    e = entorno
    e.store.fallo = fallo
    e.store.detalle = "parametro sensible " + e.token
    respuesta = e.a.post(RUTA, headers=e.headers)
    assert respuesta.status_code == 503
    assert respuesta.json()["code"] == "SESION_ATM_NO_DISPONIBLE"
    assert e.token not in respuesta.text + caplog.text
    assert not e.store.rows


def test_fallo_consulta_impide_operacion_protegida(entorno):
    entorno.store.fallo = "leer"
    assert (
        entorno.a.get("/operacion-de-prueba", headers=entorno.headers).status_code
        == 503
    )


def test_logout_concurrente_dos_instancias_solo_inserta_una_vez(entorno):
    e = entorno

    def cerrar(i):
        return (e.a if i % 2 else e.b).post(RUTA, headers=e.headers).status_code

    with ThreadPoolExecutor(max_workers=8) as pool:
        resultados = list(pool.map(cerrar, range(16)))
    assert resultados == [204] * 16
    assert len(e.store.rows) == 1
    assert len([sql for sql, _ in e.store.calls if sql.startswith("INSERT")]) == 1
    assert e.b.get("/operacion-de-prueba", headers=e.headers).status_code == 401


def test_logs_sin_token_y_openapi_sin_body(entorno, caplog):
    caplog.set_level(logging.DEBUG)
    assert entorno.a.post(RUTA, headers=entorno.headers).status_code == 204
    assert (
        entorno.b.get("/operacion-de-prueba", headers=entorno.headers).status_code
        == 401
    )
    assert entorno.token not in caplog.text
    schema = entorno.a.get("/openapi.json").json()
    op = schema["paths"][RUTA]["post"]
    assert op["operationId"] == "ATM09"
    assert "requestBody" not in op
    assert "204" in op["responses"] and "503" in op["responses"]
    assert "content" not in op["responses"]["204"]
    assert op["security"] == [{"SesionATM": []}]


def test_configuracion_rsa_ausente_falla_cerrada(entorno):
    entorno.settings.atm_jwt_private_key_pem = SecretStr("")
    assert entorno.a.post(RUTA, headers=entorno.headers).status_code == 503
    entorno.engine.assert_not_called()


def test_logout_en_aplicacion_principal_sin_cookie_workos(entorno):
    from app.main import app

    with TestClient(app, base_url="https://testserver") as client:
        respuesta = client.post(RUTA, headers=entorno.headers)
    assert respuesta.status_code == 204
    assert respuesta.content == b""
    assert len(entorno.store.rows) == 1
    assert (
        entorno.b.get("/operacion-de-prueba", headers=entorno.headers).status_code
        == 401
    )
