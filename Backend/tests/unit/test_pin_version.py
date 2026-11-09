"""Versión firmada y autorización compartida; SQL y red siempre bloqueados."""

from dataclasses import replace
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from pydantic import SecretStr
from sqlalchemy.exc import SQLAlchemyError

from app.core.config.settings import Settings
from app.core.security.pin_version import (
    PinVersionNoDisponible,
    validar_version,
    version_desde_fecha,
)
from app.modules.atm import repository, session
from app.modules.atm.schemas import CuentaATM
from app.modules.atm.service import AccesoATMValidado
from app.modules.tarjetas import repository as tarjetas_repo
from tests.pin_version import FECHA_PIN, VERSION_PIN


@pytest.fixture
def lab(monkeypatch):
    def prohibited(*_a, **_kw):
        raise AssertionError("SQL externo prohibido")

    monkeypatch.setattr("pyodbc.connect", prohibited)
    monkeypatch.setattr("app.core.database.db.create_engine", prohibited)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    cfg = Settings.model_construct(
        atm_jwt_private_key_pem=SecretStr(pem),
        atm_jwt_issuer="urn:lab:pin-version",
        atm_jwt_audience="urn:lab:pin-version:operaciones",
    )
    monkeypatch.setattr(session, "get_settings", lambda: cfg)
    acceso = AccesoATMValidado(
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
    engine = MagicMock()
    factory = MagicMock(return_value=engine)
    monkeypatch.setattr(session, "get_engine", factory)
    row = {
        "fecha_asignacion": FECHA_PIN,
        "tiene_pin_asignado": True,
        "estado_pin": "Activo",
        "intentos_fallidos": 0,
        "requiere_cambio": False,
    }
    read = MagicMock(side_effect=lambda *_: dict(row))
    monkeypatch.setattr(repository, "obtener_asignacion_pin_actual", read)
    monkeypatch.setattr(repository, "sesion_atm_revocada", lambda *_: False)
    token = session.emitir_sesion_atm(acceso).session_token
    return SimpleNamespace(
        key=key,
        cfg=cfg,
        acceso=acceso,
        engine=factory,
        row=row,
        read=read,
        token=token,
        sesion=session.validar_jwt_atm(token),
    )


@pytest.mark.parametrize(
    "fecha", [None, date(2026, 1, 1), "2026-01-01", datetime.now(UTC)]
)
def test_fecha_invalida_no_inventa_version(fecha):
    with pytest.raises(PinVersionNoDisponible):
        version_desde_fecha(fecha)


@pytest.mark.parametrize(
    "value", [None, 123, "", "2026-11-01T10:00:00", VERSION_PIN + "Z"]
)
def test_version_no_canonica(value):
    with pytest.raises(PinVersionNoDisponible):
        validar_version(value)


def test_precision_conservada():
    fecha = FECHA_PIN.replace(microsecond=7000)
    assert validar_version(version_desde_fecha(fecha)) == "2026-11-01T10:00:00.007000"


def test_claim_firmado_sin_cambiar_contrato_response(lab):
    claims = jwt.decode(
        lab.token,
        lab.key.public_key(),
        algorithms=["RS256"],
        issuer=lab.cfg.atm_jwt_issuer,
        audience=lab.cfg.atm_jwt_audience,
    )
    assert claims["pinVersion"] == VERSION_PIN
    assert (
        session.require_sesion_operativa(session.require_sesion_pin_actual(lab.sesion))
        is lab.sesion
    )


@pytest.mark.parametrize(
    "fecha", [None, FECHA_PIN.replace(day=2), FECHA_PIN.replace(day=31, month=10)]
)
def test_version_distinta_o_nula_cierra_acceso(lab, fecha):
    lab.row["fecha_asignacion"] = fecha
    with pytest.raises(HTTPException) as exc:
        session.require_sesion_pin_actual(lab.sesion)
    assert exc.value.status_code == (503 if fecha is None else 401)


@pytest.mark.parametrize(
    "changes",
    [
        {"estado_pin": "Bloqueado"},
        {"intentos_fallidos": 3},
        {"intentos_fallidos": -1},
        {"tiene_pin_asignado": False},
        {"requiere_cambio": None},
    ],
)
def test_pin_no_operativo_no_consume_intentos(lab, changes):
    lab.row.update(changes)
    before = dict(lab.row)
    with pytest.raises(HTTPException) as exc:
        session.require_sesion_pin_actual(lab.sesion)
    assert exc.value.status_code == 403
    assert lab.row == before


def test_cambio_actual_obligatorio_no_confia_en_claim_antiguo(lab):
    lab.row["requiere_cambio"] = True
    with pytest.raises(HTTPException) as exc:
        session.require_sesion_pin_actual(lab.sesion)
    assert exc.value.status_code == 403
    assert isinstance(exc.value.detail, dict)
    assert cast(dict[str, Any], exc.value.detail)["code"] == "PIN_CAMBIO_REQUERIDO"


def test_restringida_actual_conserva_403(lab):
    token = session.emitir_sesion_atm(
        replace(lab.acceso, cuentas=[], cambio_pin_requerido=True)
    ).session_token
    lab.row["requiere_cambio"] = True
    sesion = session.require_sesion_pin_actual(session.validar_jwt_atm(token))
    with pytest.raises(HTTPException) as exc:
        session.require_sesion_operativa(sesion)
    assert isinstance(exc.value.detail, dict)
    assert cast(dict[str, Any], exc.value.detail)["code"] == "PIN_CAMBIO_REQUERIDO"


def test_fallo_seguridad_no_filtra_datos(lab):
    lab.read.side_effect = SQLAlchemyError("no devolver: " + lab.token)
    with pytest.raises(HTTPException) as exc:
        session.require_sesion_pin_actual(lab.sesion)
    assert exc.value.status_code == 503
    assert lab.token not in str(exc.value.detail)


def test_legacy_solo_parseable_para_logout(lab):
    claims = jwt.decode(
        lab.token,
        lab.key.public_key(),
        algorithms=["RS256"],
        audience=lab.cfg.atm_jwt_audience,
    )
    claims.pop("pinVersion")
    token = jwt.encode(claims, lab.key, algorithm="RS256")
    sesion = session.validar_jwt_atm(token)
    assert sesion.pin_version is None
    with pytest.raises(HTTPException) as exc:
        session.require_sesion_pin_actual(sesion)
    assert exc.value.status_code == 401
    lab.engine.assert_not_called()


def test_emisor_rechaza_version_ausente(lab):
    with pytest.raises(HTTPException) as exc:
        session.emitir_sesion_atm(replace(lab.acceso, pin_version=None))
    assert exc.value.status_code == 503


@pytest.mark.parametrize("value", [None, True, 123, "", "2026-11-01T10:00:00"])
def test_claim_pin_version_malformado_no_se_acepta(lab, value):
    claims = jwt.decode(
        lab.token,
        lab.key.public_key(),
        algorithms=["RS256"],
        audience=lab.cfg.atm_jwt_audience,
    )
    claims["pinVersion"] = value
    token = jwt.encode(claims, lab.key, algorithm="RS256")
    with pytest.raises(HTTPException) as exc:
        session.validar_jwt_atm(token)
    assert exc.value.status_code == 401
    lab.engine.assert_not_called()


def test_lectura_estado_actual_no_recupera_criptografia():
    conn = MagicMock()
    conn.execute.return_value.mappings.return_value.one_or_none.return_value = None
    assert repository.obtener_asignacion_pin_actual(conn, 301) is None
    sql, params = conn.execute.call_args.args
    assert params == {"id_tarjeta": 301}
    assert "FechaAsignacion" in str(sql)
    assert all(
        word not in str(sql)
        for word in ("PINOffset", "ReferenciaClavePVK", "PanCifrado")
    )


def test_repositorio_no_avance_nunca_hace_commit():
    conn = MagicMock()
    conn.execute.return_value.scalar_one.return_value = None
    with pytest.raises(PinVersionNoDisponible):
        tarjetas_repo.guardar_pin_generado(conn, 301, "0042", "LAB-PVK", True)
    conn.commit.assert_not_called()
    conn.rollback.assert_not_called()  # El llamador posee la transacción.
