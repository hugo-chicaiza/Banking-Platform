"""Integración LOCAL: servicios, HSM y JWT reales; driver transaccional simulado.

No ejecuta T-SQL: prueba el flujo y los fallos con un doble serializado. No
demuestra locks ni sintaxis del motor Azure SQL y nunca abre conexiones externas.
"""

import asyncio
import copy
import hashlib
import socket
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta
from threading import Event, RLock
from types import SimpleNamespace
from typing import Any, cast

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Connection
from sqlalchemy.exc import DBAPIError

from app.core.config.settings import Settings
from app.modules.atm import router, service, session
from app.modules.atm.schemas import CuentaATM
from app.modules.tarjetas import service as tarjetas
from tests.pin_version import FECHA_PIN, VERSION_PIN, DriverLimitesSQL
from tests.tarjetas_hsm import HSM, PAN


class Result:
    def __init__(self, value: Any):
        self.value = value

    def scalar_one(self):
        return self.value

    def scalar_one_or_none(self):
        return self.value

    def mappings(self):
        return self

    def first(self):
        return self.value

    def one_or_none(self):
        return self.value


class Driver:
    def __init__(self):
        self.lock = RLock()
        block, reference = HSM.construir_pin_block("7392", PAN)
        offset, pvk = HSM.generar_offset(block, reference, PAN)
        self.row: dict[str, Any] | None = {
            "fecha_asignacion": FECHA_PIN,
            "pin_offset": offset,
            "referencia_clave_pvk": pvk,
            "tiene_pin_asignado": True,
            "estado_pin": "Activo",
            "intentos_fallidos": 0,
            "requiere_cambio": False,
        }
        self.revoked: set[str] = set()
        self.clock: deque[datetime | None] = deque(
            [FECHA_PIN + timedelta(milliseconds=10)]
        )
        self.failure: str | None = None
        self.read_locked: Event | None = None
        self.release_read = Event()
        self.writer_started = Event()

    def connect(self):
        return self.begin()

    @contextmanager
    def begin(self):
        conn = LocalConnection(self)
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise


class LocalConnection:
    def __init__(self, driver: Driver):
        self.connection = SimpleNamespace(driver_connection=DriverLimitesSQL())
        self.invalidated = False
        self.d = driver
        self.owned = False
        self.before: Any = None

    def execute(self, statement, params):
        sql = str(statement)
        assignment = "DECLARE @Existe" in sql
        if assignment:
            self.d.writer_started.set()
        if not self.owned:
            self.d.lock.acquire()
            self.owned = True
            self.before = copy.deepcopy((self.d.row, self.d.revoked))
        if assignment:
            assert "UPDLOCK, HOLDLOCK" in sql and "@Ahora <= @Anterior" in sql
            now = self.d.clock.popleft()
            old = self.d.row
            if now is None or (
                old is not None
                and (
                    (old["fecha_asignacion"] is None and old["tiene_pin_asignado"])
                    or (
                        old["fecha_asignacion"] is not None
                        and now <= old["fecha_asignacion"]
                    )
                )
            ):
                return Result(None)
            self.d.row = {
                "fecha_asignacion": now,
                "pin_offset": params["offset"],
                "referencia_clave_pvk": params["pvk"],
                "tiene_pin_asignado": True,
                "estado_pin": "Activo",
                "intentos_fallidos": 0,
                "requiere_cambio": params["requiere_cambio"],
            }
            if self.d.failure == "write":
                raise DBAPIError("lab", None, RuntimeError("fallo simulado"))
            return Result(now)
        if "SesionesATMRevocadas" in sql:
            if "INSERT INTO" in sql:
                self.d.revoked.add(params["jti"])
                return Result(None)
            return Result(1 if params["jti"] in self.d.revoked else None)
        if "UPDATE Tarjetas.TarjetaPIN" in sql:
            assert self.d.row is not None
            self.d.row["intentos_fallidos"] = 0
            return Result({"intentos_fallidos": 0, "estado_pin": "Activo"})
        assert "FROM Tarjetas.TarjetaPIN" in sql
        row = copy.deepcopy(self.d.row)
        if "UPDLOCK, ROWLOCK" in sql and self.d.read_locked is not None:
            self.d.read_locked.set()
            if not self.d.release_read.wait(3):
                raise TimeoutError("Coordinación local excedida")
        return Result(row)

    def commit(self):
        if self.owned:
            if self.d.failure == "commit":
                raise DBAPIError("lab", None, RuntimeError("fallo antes de commit"))
            self.owned = False
            self.d.lock.release()
            if self.d.failure == "commit_ack":
                raise DBAPIError("lab", None, RuntimeError("confirmación perdida"))

    def invalidate(self):
        self.invalidated = True

    def rollback(self):
        if self.owned:
            self.d.row, self.d.revoked = self.before
            self.owned = False
            self.d.lock.release()


@pytest.fixture
def lab(monkeypatch):
    def prohibited(*_a, **_kw):
        raise AssertionError("SQL/red real prohibidos")

    original = socket.socket.connect

    def local(sock, address):
        if isinstance(address, tuple) and address[0] in {"127.0.0.1", "::1"}:
            return original(sock, address)
        return prohibited()

    monkeypatch.setattr(socket.socket, "connect", local)
    monkeypatch.setattr("pyodbc.connect", prohibited)
    monkeypatch.setattr("app.core.database.db.create_engine", prohibited)
    driver = Driver()
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    cfg = Settings.model_construct(
        atm_jwt_private_key_pem=SecretStr(pem),
        atm_jwt_issuer="urn:lab:local",
        atm_jwt_audience="urn:lab:local:atm",
    )
    monkeypatch.setattr(session, "get_settings", lambda: cfg)

    def security(name):
        assert name == "seguridad"
        return driver

    monkeypatch.setattr(session, "get_engine", security)
    monkeypatch.setattr(service, "get_engine", security)
    monkeypatch.setattr(service, "obtener_hsm", lambda: HSM)
    monkeypatch.setattr(service, "pan_de_prueba", lambda *_: PAN)
    monkeypatch.setattr(tarjetas, "pan_de_prueba", lambda *_: PAN)
    monkeypatch.setattr(
        service,
        "validar_tarjeta",
        lambda *_: {
            "estado_tarjeta": "Activa",
            "hash_numero_tarjeta": hashlib.sha256(PAN.encode()).digest(),
        },
    )
    acceso = service.AccesoATMValidado(
        7,
        301,
        "Ficticio",
        [
            CuentaATM(
                id_cuenta=501,
                numero_cuenta_enmascarado="****0501",
                tipo_cuenta="Ahorro",
            )
        ],
        pin_version=VERSION_PIN,
    )
    app = FastAPI()
    app.include_router(router.router, prefix="/api/v1")

    @app.get(
        "/local/operacion", dependencies=[Depends(session.require_sesion_operativa)]
    )
    def operation():
        return {"ok": True}

    @app.get(
        "/local/reintento", dependencies=[Depends(session.require_sesion_operativa)]
    )
    def retry():
        return {"ok": True}

    with TestClient(app, base_url="https://testserver") as http:
        yield SimpleNamespace(driver=driver, key=key, acceso=acceso, http=http)


def regenerate(lab, tipo):
    conn = LocalConnection(lab.driver)
    tarjetas._generar_pin(cast(Connection, conn), 301, tipo, HSM, "Regeneracion")


def headers(lab, acceso=None):
    token = session.emitir_sesion_atm(acceso or lab.acceso).session_token
    return {"Authorization": "Bearer " + token}


@pytest.mark.parametrize("tipo", ["Debito", "Credito"])
def test_regeneracion_invalida_operacion_y_reintento_permite_logout(lab, tipo, caplog):
    h = headers(lab)
    assert lab.http.get("/local/operacion", headers=h).status_code == 200
    regenerate(lab, tipo)
    assert lab.driver.row is not None
    assert lab.driver.row["requiere_cambio"] is (tipo == "Debito")
    # Volver a autenticarse con la nueva asignación funciona; nunca cambiar
    # retrospectivamente la versión del JWT anterior.
    natural = HSM._pin_natural(PAN)
    generated = "".join(
        str((int(n) + int(o)) % 10)
        for n, o in zip(natural, lab.driver.row["pin_offset"], strict=True)
    )
    block, reference = HSM.construir_pin_block(generated, PAN)
    verified = asyncio.run(
        service.autenticar_pin_ficticio_atm(
            cast(Connection, None), 301, block, reference
        )
    )
    acceso = replace(
        lab.acceso,
        pin_version=verified.pin_version,
        cambio_pin_requerido=verified.requiere_cambio,
        cuentas=[] if verified.requiere_cambio else lab.acceso.cuentas,
    )
    fresh = headers(lab, acceso)
    assert lab.http.get("/local/operacion", headers=fresh).status_code == (
        403 if tipo == "Debito" else 200
    )
    for path in ("/local/operacion", "/local/reintento"):
        assert lab.http.get(path, headers=h).status_code == 401
    for _ in range(2):
        assert lab.http.post("/api/v1/atm/logout", headers=h).status_code == 204
    assert len(lab.driver.revoked) == 1
    assert h["Authorization"] not in caplog.text
    assert fresh["Authorization"] not in caplog.text


def test_sesion_antigua_no_revive_al_quitar_cambio_requerido(lab):
    old = headers(lab)
    regenerate(lab, "Debito")
    lab.driver.clock.append(FECHA_PIN + timedelta(milliseconds=20))
    # Modela una segunda asignación no temporal, como hará el futuro ATM-06.
    regenerate(lab, "Credito")
    assert lab.driver.row is not None and lab.driver.row["requiere_cambio"] is False
    assert lab.http.get("/local/reintento", headers=old).status_code == 401


@pytest.mark.parametrize(
    "candidate", [None, FECHA_PIN, FECHA_PIN - timedelta(seconds=1)]
)
def test_fecha_no_avanza_no_cambia_datos(lab, candidate):
    lab.driver.clock = deque([candidate])
    before = copy.deepcopy(lab.driver.row)
    with pytest.raises(HTTPException) as exc:
        regenerate(lab, "Credito")
    assert exc.value.status_code == 503
    assert lab.driver.row == before


def test_asignacion_existente_sin_fecha_falla_cerrada(lab):
    assert lab.driver.row is not None
    lab.driver.row["fecha_asignacion"] = None
    before = copy.deepcopy(lab.driver.row)
    with pytest.raises(HTTPException) as exc:
        regenerate(lab, "Debito")
    assert exc.value.status_code == 503
    assert lab.driver.row == before


def test_primera_asignacion(lab):
    lab.driver.row = None
    regenerate(lab, "Debito")
    assert lab.driver.row is not None
    assert lab.driver.row["requiere_cambio"] is True


@pytest.mark.parametrize("failure", ["write", "commit"])
def test_fallo_seguridad_revierte_asignacion_completa(lab, failure):
    before = copy.deepcopy(lab.driver.row)
    lab.driver.failure = failure
    with pytest.raises(HTTPException):
        regenerate(lab, "Debito")
    assert lab.driver.row == before


def test_regeneraciones_concurrentes_serializadas(lab):
    lab.driver.clock = deque(
        [FECHA_PIN + timedelta(milliseconds=10), FECHA_PIN + timedelta(milliseconds=20)]
    )
    h = headers(lab)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(regenerate, lab, tipo) for tipo in ("Debito", "Credito")]
        for future in futures:
            future.result(timeout=5)
    assert lab.driver.row is not None
    assert lab.driver.row["fecha_asignacion"] == FECHA_PIN + timedelta(milliseconds=20)
    assert lab.http.get("/local/operacion", headers=h).status_code == 401


def test_regeneraciones_concurrentes_mismo_tick_no_reutilizan_version(lab):
    next_date = FECHA_PIN + timedelta(milliseconds=10)
    lab.driver.clock = deque([next_date, next_date])

    def attempt():
        try:
            regenerate(lab, "Credito")
            return 204
        except HTTPException as exc:
            return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: attempt(), range(2)))
    assert sorted(results) == [204, 503]
    assert lab.driver.row is not None
    assert lab.driver.row["fecha_asignacion"] == next_date


def test_autenticacion_concurrente_con_regeneracion_no_sustituye_version(lab):
    block, reference = HSM.construir_pin_block("7392", PAN)
    lab.driver.read_locked = Event()

    def authenticate():
        return asyncio.run(
            service.autenticar_pin_ficticio_atm(
                cast(Connection, None), 301, block, reference
            )
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        authentication = pool.submit(authenticate)
        try:
            assert lab.driver.read_locked.wait(3)
            regeneration = pool.submit(regenerate, lab, "Credito")
            assert lab.driver.writer_started.wait(3)
        finally:
            lab.driver.release_read.set()
        verified = authentication.result(timeout=5)
        regeneration.result(timeout=5)
    assert verified.pin_version == VERSION_PIN
    h = headers(lab, replace(lab.acceso, pin_version=verified.pin_version))
    assert lab.http.get("/local/operacion", headers=h).status_code == 401


def test_legacy_sin_version_no_opera_y_puede_cerrar(lab):
    h = headers(lab)
    claims = jwt.decode(
        h["Authorization"].split()[1],
        lab.key.public_key(),
        algorithms=["RS256"],
        audience="urn:lab:local:atm",
    )
    claims.pop("pinVersion")
    token = jwt.encode(claims, lab.key, algorithm="RS256")
    h = {"Authorization": "Bearer " + token}
    assert lab.http.get("/local/operacion", headers=h).status_code == 401
    assert lab.http.post("/api/v1/atm/logout", headers=h).status_code == 204


def test_revocacion_se_aplica_antes_de_la_version_actual(lab):
    h = headers(lab)
    assert lab.http.get("/local/operacion", headers=h).status_code == 200
    assert lab.http.post("/api/v1/atm/logout", headers=h).status_code == 204
    assert lab.http.get("/local/operacion", headers=h).status_code == 401
    assert lab.http.get("/local/reintento", headers=h).status_code == 401


def test_confirmacion_perdida_no_repite_asignacion_ni_revierte_commit(lab):
    old = headers(lab)
    lab.driver.failure = "commit_ack"
    with pytest.raises(HTTPException) as exc:
        regenerate(lab, "Credito")
    assert exc.value.status_code == 503
    assert "reconciliación" in str(exc.value.detail)
    assert lab.driver.row is not None
    assert lab.driver.row["fecha_asignacion"] > FECHA_PIN
    assert not lab.driver.clock  # Una sola asignación, sin reintento automático.
    lab.driver.failure = None
    assert lab.http.get("/local/operacion", headers=old).status_code == 401
