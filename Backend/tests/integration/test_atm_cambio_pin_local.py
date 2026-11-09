"""Flujo local con HSM real y persistencia transaccional en memoria.

No interpreta T-SQL ni demuestra bloqueos del motor SQL Server.
"""

import copy
import socket
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from threading import RLock
from types import SimpleNamespace
from typing import cast
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from app.core.security.hsm import HsmNoDisponible, PinBlockInvalido
from app.core.security.pin_version import version_desde_fecha
from app.modules.atm import cambio_pin_service as svc
from app.modules.atm import repository, router, service, session, terminal_auth
from app.modules.atm.schemas import AtmCambioPinRequest
from app.modules.tarjetas.identificacion import hash_pan
from tests.tarjetas_hsm import HSM, PAN


class Conexion:
    def __init__(self, lab, base):
        self.lab, self.base = lab, base
        self.before = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    @contextmanager
    def begin(self):
        self.lab.locks[self.base].acquire()
        self.before = copy.deepcopy(self.lab.data[self.base])
        try:
            yield self
            if self.before is not None:
                self.commit()
        except BaseException:
            if self.before is not None:
                self.lab.data[self.base] = self.before
                self.before = None
                self.lab.locks[self.base].release()
            raise

    def commit(self):
        self.lab.commits[self.base] += 1
        numero = self.lab.commits[self.base]
        modo = self.lab.fallos.pop((self.base, numero), None)
        if modo == "antes":
            raise SQLAlchemyError("Fallo sintetico")
        self.before = None
        self.lab.locks[self.base].release()
        if modo == "despues":
            raise SQLAlchemyError("Confirmacion sintetica perdida")


class Laboratorio:
    def __init__(self):
        self.locks = {k: RLock() for k in ("cooperativa", "seguridad")}
        self.commits = {k: 0 for k in self.locks}
        self.fallos = {}
        self.hsm_calls = 0
        self.fecha = datetime(2026, 11, 1, 10)
        self.data = {
            "cooperativa": {"estado": "Activa", "historial": [], "marcador": None},
            "seguridad": {
                "pin": {
                    "fecha_asignacion": self.fecha,
                    "estado_pin": "Activo",
                    "intentos_fallidos": 0,
                    "tiene_pin_asignado": True,
                    "requiere_cambio": False,
                    "pin_offset": HSM.generar_offset(
                        *HSM.construir_pin_block("4826", PAN), PAN
                    )[0],
                    "referencia_clave_pvk": "SIM-PVK-01",
                },
                "op": None,
                "revocada": False,
            },
        }
        self.sesion = session.SesionATM(
            str(uuid4()),
            datetime.now(UTC) + timedelta(seconds=300),
            1,
            1,
            (1,),
            False,
            version_desde_fecha(self.fecha),
        )
        self.terminal = terminal_auth.TerminalAutenticado(
            "laboratorio", "ATM00001", 900, b""
        )
        self.body = self.solicitud("4826", "9274")

    @staticmethod
    def solicitud(actual, nuevo):
        return AtmCambioPinRequest.model_validate(
            {
                "encryptedPinBlockActual": HSM.construir_pin_block(actual, PAN)[0],
                "encryptedPinBlockNuevo": HSM.construir_pin_block(nuevo, PAN)[0],
                "keyReference": "TEST-KEY-01",
            }
        )

    @property
    def seg(self):
        return self.data["seguridad"]

    @property
    def coop(self):
        return self.data["cooperativa"]

    def cambiar(self, entrada=None, sesion=None):
        svc.cambiar_pin(
            sesion or self.sesion, self.terminal, entrada or self.body, "127.0.0.1"
        )

    def recuperar(self):
        svc.recuperar_cambio_pin(str(self.seg["op"]["IdOperacion"]))


@pytest.fixture
def lab(monkeypatch):
    lab = Laboratorio()
    monkeypatch.setattr(
        socket, "create_connection", lambda *a, **kw: pytest.fail("Red prohibida")
    )

    @contextmanager
    def conexiones():
        yield Conexion(lab, "cooperativa"), Conexion(lab, "seguridad")

    monkeypatch.setattr(svc, "_conexiones", conexiones)
    monkeypatch.setattr(
        svc,
        "get_engine",
        lambda base: SimpleNamespace(connect=lambda: Conexion(lab, base)),
    )

    @contextmanager
    def limite(conn):
        yield

    monkeypatch.setattr(svc, "sesion_sql_acotada", limite)
    monkeypatch.setattr(svc, "revalidar_terminal", lambda t: None)
    monkeypatch.setattr(svc, "obtener_hsm", lambda: HSM)
    monkeypatch.setattr(service, "pan_de_prueba", lambda *a: PAN)
    monkeypatch.setattr(
        service, "validar_terminal", lambda *a: {"id_atm": 1, "id_canal": 1}
    )

    def tarjeta(*a):
        if lab.coop["estado"] not in ("Activa", "Generada"):
            raise HTTPException(423)
        return {
            "estado_tarjeta": lab.coop["estado"],
            "tipo_tarjeta": "Debito",
            "hash_numero_tarjeta": hash_pan(PAN),
            "fecha_expiracion": date(2099, 1, 1),
        }

    monkeypatch.setattr(service, "validar_tarjeta", tarjeta)
    monkeypatch.setattr(
        repository,
        "obtener_pin_para_verificacion",
        lambda *a: copy.deepcopy(lab.seg["pin"]),
    )
    monkeypatch.setattr(
        repository, "sesion_atm_revocada", lambda *a: lab.seg["revocada"]
    )

    def resultado(conn, tarjeta, correcto):
        assert not correcto
        pin = lab.seg["pin"]
        pin["intentos_fallidos"] += 1
        if pin["intentos_fallidos"] >= 3:
            pin["estado_pin"] = "Bloqueado"
        return pin

    monkeypatch.setattr(repository, "guardar_resultado_pin", resultado)
    monkeypatch.setattr(
        repository,
        "bloquear_tarjeta_por_pin",
        lambda *a: lab.coop.update(estado="Bloqueada"),
    )

    def revocar(*a):
        lab.seg["revocada"] = True

    monkeypatch.setattr(repository, "revocar_sesion_atm", revocar)

    def guardar(conn, tarjeta, offset, pvk, requiere):
        assert lab.seg["op"] is None
        lab.hsm_calls += 1
        lab.seg["pin"].update(
            pin_offset=offset,
            referencia_clave_pvk=pvk,
            requiere_cambio=requiere,
            intentos_fallidos=0,
            fecha_asignacion=lab.fecha + timedelta(seconds=1),
        )

    monkeypatch.setattr(svc, "guardar_pin_generado", guardar)
    r = svc.repo
    monkeypatch.setattr(r, "bloquear_tarjeta", lambda *a: None)
    monkeypatch.setattr(
        r,
        "hay_pendiente",
        lambda *a: (
            lab.seg["op"] is not None and lab.seg["op"]["Estado"] != "COMPLETADA"
        ),
    )
    monkeypatch.setattr(
        r,
        "identificar_operacion",
        lambda conn, op: (
            1 if lab.seg["op"] and str(lab.seg["op"]["IdOperacion"]) == op else None
        ),
    )
    monkeypatch.setattr(r, "leer_operacion", lambda *a: copy.deepcopy(lab.seg["op"]))
    monkeypatch.setattr(
        r, "leer_marcador", lambda *a: copy.deepcopy(lab.coop["marcador"])
    )

    def insertar(conn, d):
        lab.seg["op"] = {
            "IdOperacion": d["operacion"],
            "ID_Tarjeta": 1,
            "IdATM": 1,
            "IdCanal": 1,
            "ActorAuditoria": d["actor"],
            "DireccionIP": d["ip"],
            "JtiOrigen": d["jti"],
            "ExpiracionSesionUTC": d["expiracion"],
            "VersionNueva": lab.seg["pin"]["fecha_asignacion"],
            "RequiereActivacion": d["activar"],
            "Estado": "PIN_CONFIRMADO",
        }

    monkeypatch.setattr(r, "insertar_operacion", insertar)
    monkeypatch.setattr(
        r,
        "registrar_fecha_cambio",
        lambda *a: lab.seg["pin"].update(
            fecha_ultimo_cambio=lab.seg["pin"]["fecha_asignacion"]
        ),
    )

    def aplicar(conn, op):
        assert lab.seg["pin"]["requiere_cambio"]
        if op["RequiereActivacion"]:
            assert lab.coop["estado"] == "Generada"
            lab.coop["estado"] = "Activa"
            lab.coop["historial"].append("Activacion")
        lab.coop["historial"].append("CambioPin")
        lab.coop["marcador"] = {**op, "IdTarjeta": 1, "VersionPIN": op["VersionNueva"]}

    monkeypatch.setattr(r, "aplicar_cooperativa", aplicar)
    monkeypatch.setattr(
        r, "avanzar", lambda *a: lab.seg["op"].update(Estado="COOP_CONFIRMADA")
    )

    def finalizar(conn, op):
        assert lab.coop["marcador"] is not None
        assert lab.seg["pin"]["fecha_asignacion"] == op["VersionNueva"]
        lab.seg["pin"]["requiere_cambio"] = False
        lab.seg["op"]["Estado"] = "COMPLETADA"

    monkeypatch.setattr(r, "finalizar", finalizar)
    return lab


@pytest.mark.parametrize("restringida", [False, True])
def test_cambio_real_hsm_y_activacion(lab, restringida):
    if restringida:
        lab.coop["estado"] = "Generada"
        lab.seg["pin"]["requiere_cambio"] = True
        lab.sesion = replace(lab.sesion, cambio_pin_requerido=True, cuentas=())
    lab.cambiar()
    assert lab.seg["op"]["Estado"] == "COMPLETADA"
    assert not lab.seg["pin"]["requiere_cambio"]
    assert lab.seg["revocada"]
    assert lab.seg["pin"]["fecha_asignacion"] > lab.fecha
    assert lab.coop["historial"] == (
        ["Activacion", "CambioPin"] if restringida else ["CambioPin"]
    )
    assert HSM.verificar_pin(
        lab.body.encrypted_pin_block_nuevo.get_secret_value(),
        "TEST-KEY-01",
        PAN,
        lab.seg["pin"]["pin_offset"],
        "SIM-PVK-01",
    )


def test_pin_incorrecto_hasta_bloqueo(lab):
    for status in (401, 401, 423):
        with pytest.raises(HTTPException) as e:
            lab.cambiar(lab.solicitud("5837", "9274"))
        assert e.value.status_code == status
    assert lab.seg["pin"]["intentos_fallidos"] == 3
    assert lab.coop["estado"] == "Bloqueada"
    assert lab.seg["op"] is None


@pytest.mark.parametrize("nuevo", ["1111", "1234", "4826"])
def test_pin_nuevo_debil_o_igual_no_consume_intentos(lab, nuevo):
    with pytest.raises(HTTPException) as e:
        lab.cambiar(lab.solicitud("4826", nuevo))
    assert e.value.status_code == 422
    detail = cast(dict[str, str], e.value.detail)
    assert detail["code"] == "PIN_DEBIL"
    assert lab.seg["pin"]["intentos_fallidos"] == 0
    assert lab.seg["op"] is None


@pytest.mark.parametrize(
    "error,status", [(HsmNoDisponible(), 503), (PinBlockInvalido(), 422)]
)
def test_errores_hsm_no_consumen_intentos(lab, monkeypatch, error, status):
    def falla(*a):
        raise error

    monkeypatch.setattr(service, "verificar_pin_atm", falla)
    with pytest.raises(HTTPException) as e:
        lab.cambiar()
    assert e.value.status_code == status
    assert lab.seg["op"] is None
    assert lab.seg["pin"]["intentos_fallidos"] == 0


@pytest.mark.parametrize("campo", ["pin_version", "revocada", "expirada"])
def test_sesion_invalida_no_cambia_pin(lab, campo):
    if campo == "revocada":
        lab.seg["revocada"] = True
    elif campo == "expirada":
        lab.sesion = replace(
            lab.sesion, fecha_expiracion=datetime.now(UTC) - timedelta(seconds=1)
        )
    else:
        lab.sesion = replace(lab.sesion, pin_version=None)
    with pytest.raises(HTTPException) as e:
        lab.cambiar()
    assert e.value.status_code == 401
    assert lab.seg["op"] is None


@pytest.mark.parametrize(
    "base,numero",
    [
        ("seguridad", 1),
        ("cooperativa", 1),
        ("cooperativa", 2),
        ("seguridad", 2),
        ("seguridad", 3),
    ],
)
@pytest.mark.parametrize("modo", ["antes", "despues"])
def test_fallos_y_commit_ambiguo_recuperables(lab, base, numero, modo):
    lab.fallos[base, numero] = modo
    with pytest.raises(HTTPException) as e:
        lab.cambiar()
    assert e.value.status_code == 503
    if lab.seg["op"] is None:
        assert not lab.seg["revocada"]
        assert lab.seg["pin"]["fecha_asignacion"] == lab.fecha
        return
    assert lab.seg["pin"]["requiere_cambio"] or lab.seg["op"]["Estado"] == "COMPLETADA"
    lab.recuperar()
    lab.recuperar()
    assert lab.seg["op"]["Estado"] == "COMPLETADA"
    assert lab.coop["historial"] == ["CambioPin"]
    assert lab.hsm_calls == 1


def test_concurrencia_y_repeticion(lab):
    def ejecutar(_):
        try:
            lab.cambiar()
            return 204
        except HTTPException as e:
            return e.status_code

    with ThreadPoolExecutor(2) as executor:
        estados = list(executor.map(ejecutar, range(2)))
    assert sorted(estados) == [204, 401]
    assert lab.hsm_calls == 1
    assert lab.coop["historial"] == ["CambioPin"]


def test_recuperacion_no_habilita_version_posterior(lab, monkeypatch):
    lab.fallos["cooperativa", 2] = "antes"
    with pytest.raises(HTTPException):
        lab.cambiar()
    lab.seg["pin"]["fecha_asignacion"] += timedelta(seconds=1)
    with pytest.raises(HTTPException):
        lab.recuperar()
    assert lab.seg["pin"]["requiere_cambio"]


def test_http_204_y_cuerpo_sensible_sanitizado(lab, caplog):
    app = FastAPI()
    app.include_router(router.router, prefix="/api/v1")
    app.dependency_overrides[session.require_sesion_atm] = lambda: lab.sesion
    app.dependency_overrides[terminal_auth.require_terminal] = lambda: lab.terminal
    with TestClient(app, base_url="https://testserver") as client:
        sensible = "NO_DEBE_APARECER_EN_RESPUESTAS"
        bad = client.post(
            "/api/v1/atm/cambio-pin", json={"encryptedPinBlockActual": sensible}
        )
        assert bad.status_code == 422
        assert sensible not in bad.text + caplog.text
        response = client.post(
            "/api/v1/atm/cambio-pin",
            json={
                "encryptedPinBlockActual": lab.body.encrypted_pin_block_actual.get_secret_value(),
                "encryptedPinBlockNuevo": lab.body.encrypted_pin_block_nuevo.get_secret_value(),
                "keyReference": "TEST-KEY-01",
            },
        )
        assert response.status_code == 204
        assert response.content == b""
        for secreto in (
            PAN,
            lab.sesion.jti,
            lab.body.encrypted_pin_block_actual.get_secret_value(),
            lab.body.encrypted_pin_block_nuevo.get_secret_value(),
        ):
            assert secreto not in caplog.text + response.text


def test_hsm_rechaza_longitud_no_soportada():
    bloque, ref = HSM.construir_pin_block("482673", PAN)
    with pytest.raises(PinBlockInvalido):
        HSM.verificar_pin(bloque, ref, PAN, "1234", "SIM-PVK-01")


def test_clave_no_autorizada_no_consume_intentos(lab):
    with pytest.raises(HTTPException) as e:
        lab.cambiar(lab.body.model_copy(update={"key_reference": "NO-AUTORIZADA"}))
    assert e.value.status_code == 422
    detail = cast(dict[str, str], e.value.detail)
    assert detail["code"] == "CLAVE_NO_AUTORIZADA"
    assert lab.seg["pin"]["intentos_fallidos"] == 0
    assert lab.seg["op"] is None


def test_recuperacion_no_utiliza_hsm(lab, monkeypatch):
    lab.fallos["cooperativa", 2] = "antes"
    with pytest.raises(HTTPException):
        lab.cambiar()

    def prohibido(*a):
        pytest.fail("No se permite volver a procesar PIN en recuperacion")

    monkeypatch.setattr(svc, "obtener_hsm", prohibido)
    lab.recuperar()
    assert lab.seg["op"]["Estado"] == "COMPLETADA"


@pytest.mark.parametrize("modificacion", ["bloqueo", "marcador", "revocacion"])
def test_recuperacion_inconsistente_falla_cerrado(lab, modificacion):
    lab.fallos["seguridad", 3] = "antes"
    with pytest.raises(HTTPException):
        lab.cambiar()
    if modificacion == "bloqueo":
        lab.seg["pin"]["estado_pin"] = "Bloqueado"
    elif modificacion == "marcador":
        lab.coop["marcador"]["ActorAuditoria"] = 123
    else:
        lab.seg["revocada"] = False
    with pytest.raises(HTTPException):
        lab.recuperar()
    assert lab.seg["pin"]["requiere_cambio"]


def test_openapi_documenta_cuerpo_y_doble_autenticacion():
    app = FastAPI()
    app.include_router(router.router, prefix="/api/v1")
    operacion = app.openapi()["paths"]["/api/v1/atm/cambio-pin"]["post"]
    assert operacion["security"] == [{"SesionATM": [], "APIKeyHeader": []}]
    assert "503" in operacion["responses"]
    assert "application/problem+json" in operacion["responses"]["503"]["content"]
    assert set(
        operacion["requestBody"]["content"]["application/json"]["schema"]["properties"]
    ) == {"encryptedPinBlockActual", "encryptedPinBlockNuevo", "keyReference"}


def test_recuperacion_tras_expirar_jwt_y_limpiar_revocacion(lab):
    lab.fallos["cooperativa", 2] = "antes"
    with pytest.raises(HTTPException):
        lab.cambiar()
    lab.seg["op"]["ExpiracionSesionUTC"] = datetime.now(UTC).replace(
        tzinfo=None
    ) - timedelta(seconds=1)
    lab.seg["revocada"] = False
    lab.recuperar()
    assert lab.seg["op"]["Estado"] == "COMPLETADA"


@pytest.mark.parametrize("restringida", [False, True])
def test_http_jwt_rs256_real_y_repeticion_revocada(
    lab, monkeypatch, caplog, restringida
):
    emisor = session.EmisorSesionATM(
        rsa.generate_private_key(public_exponent=65537, key_size=2048),
        "atm-laboratorio",
        "atm-laboratorio",
    )
    monkeypatch.setattr(session, "preparar_emisor_atm", lambda: emisor)
    monkeypatch.setattr(session, "get_engine", svc.get_engine)
    if restringida:
        lab.coop["estado"] = "Generada"
        lab.seg["pin"]["requiere_cambio"] = True
    ahora = int(datetime.now(UTC).timestamp())
    token = jwt.encode(
        {
            "iss": "atm-laboratorio",
            "aud": "atm-laboratorio",
            "scope": "atm",
            "iat": ahora,
            "exp": ahora + 300,
            "jti": lab.sesion.jti,
            "idATM": 1,
            "idTarjeta": 1,
            "cuentas": [] if restringida else [1],
            "cambioPinRequerido": restringida,
            "pinVersion": lab.sesion.pin_version,
        },
        emisor.clave,
        algorithm="RS256",
    )
    app = FastAPI()
    app.include_router(router.router, prefix="/api/v1")
    app.dependency_overrides[terminal_auth.require_terminal] = lambda: lab.terminal
    body = {
        "encryptedPinBlockActual": lab.body.encrypted_pin_block_actual.get_secret_value(),
        "encryptedPinBlockNuevo": lab.body.encrypted_pin_block_nuevo.get_secret_value(),
        "keyReference": "TEST-KEY-01",
    }
    with TestClient(app, base_url="https://testserver") as client:
        response = client.post(
            "/api/v1/atm/cambio-pin",
            headers={"Authorization": "Bearer " + token},
            json=body,
        )
        assert response.status_code == 204 and response.content == b""
        assert (
            client.post(
                "/api/v1/atm/cambio-pin",
                headers={"Authorization": "Bearer " + token},
                json=body,
            ).status_code
            == 401
        )
        assert token not in caplog.text


@pytest.mark.parametrize("restringida", [False, True])
def test_version_antigua_no_cambia_pin_ni_con_sesion_restringida(lab, restringida):
    lab.seg["pin"]["fecha_asignacion"] += timedelta(seconds=1)
    antigua = replace(
        lab.sesion,
        cambio_pin_requerido=restringida,
        cuentas=() if restringida else (1,),
    )
    with pytest.raises(HTTPException) as e:
        lab.cambiar(sesion=antigua)
    assert e.value.status_code == 401
    assert lab.seg["op"] is None
    assert lab.seg["pin"]["intentos_fallidos"] == 0


def test_coordinacion_pendiente_impide_sesion_operativa(lab, monkeypatch):
    monkeypatch.setattr(session, "get_engine", svc.get_engine)
    monkeypatch.setattr(
        repository,
        "obtener_asignacion_pin_actual",
        lambda *a: {**lab.seg["pin"], "coordinacion_pendiente": True},
    )
    with pytest.raises(HTTPException) as e:
        session.require_sesion_pin_actual(lab.sesion)
    assert e.value.status_code == 403


def test_ventana_agotada_entre_fases_no_habilita_pin(lab, monkeypatch):
    from unittest.mock import Mock

    lab.fallos["cooperativa", 2] = "antes"
    with pytest.raises(HTTPException):
        lab.cambiar()
    monkeypatch.setattr(svc.repo, "dentro_ventana", Mock(side_effect=[True, False]))
    with pytest.raises(svc.RecuperacionFueraVentana):
        svc.recuperar_cambio_pin(
            str(lab.seg["op"]["IdOperacion"]), max_edad_segundos=1800
        )
    assert lab.seg["op"]["Estado"] == "COOP_CONFIRMADA"
    assert lab.seg["pin"]["requiere_cambio"]
    lab.recuperar()
    assert lab.seg["op"]["Estado"] == "COMPLETADA"
    assert lab.hsm_calls == 1
