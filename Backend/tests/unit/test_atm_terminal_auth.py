import base64
import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.core.config.settings import Settings
from app.modules.atm import terminal_auth as auth
from scripts import atm_terminal_credentials as herramienta


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    e = MagicMock()
    e.path = tmp_path / "registro.json"
    e.id = secrets.token_urlsafe(12)
    e.secret = secrets.token_urlsafe(32)
    e.credential = (e.id + "." + e.secret).encode()
    ahora = datetime.now(UTC)
    e.registro = {
        e.id: {
            "codigoATM": "ATM00001",
            "sha256": hashlib.sha256(e.secret.encode()).hexdigest(),
            "enabled": True,
            "notBefore": (ahora - timedelta(minutes=1)).isoformat(),
            "expiresAt": (ahora + timedelta(days=1)).isoformat(),
            "auditUserId": 900,
        }
    }
    e.path.write_text(json.dumps(e.registro), encoding="utf-8")
    e.settings = Settings.model_construct(atm_terminal_credentials_file=str(e.path))
    monkeypatch.setattr(auth, "get_settings", lambda: e.settings)
    return e


def test_credencial_valida_y_contexto_no_contiene_secreto(entorno):
    e = entorno
    terminal = auth.autenticar_credencial(e.credential)
    assert terminal.codigo_atm == "ATM00001"
    assert terminal.audit_user_id == 900
    assert e.secret not in repr(terminal)
    auth.revalidar_terminal(terminal)


@pytest.mark.parametrize(
    "fallo",
    ["secreto", "id", "caducada", "revocada", "futura", "formato", "no_canonica"],
)
def test_rechazos_genericos(entorno, fallo):
    e = entorno
    valor = e.credential
    if fallo == "secreto":
        valor = (e.id + "." + secrets.token_urlsafe(32)).encode()
    elif fallo == "id":
        valor = (secrets.token_urlsafe(12) + "." + e.secret).encode()
    elif fallo == "caducada":
        e.registro[e.id]["expiresAt"] = (
            datetime.now(UTC) - timedelta(seconds=1)
        ).isoformat()
    elif fallo == "revocada":
        e.registro[e.id]["enabled"] = False
    elif fallo == "futura":
        e.registro[e.id]["notBefore"] = (
            datetime.now(UTC) + timedelta(hours=1)
        ).isoformat()
    elif fallo == "formato":
        valor = b"incorrecto"
    else:
        # 43 caracteres válidos pero bits de relleno no canónicos.
        secreto = e.secret[:-1] + "B"
        valor = (e.id + "." + secreto).encode()
    e.path.write_text(json.dumps(e.registro), encoding="utf-8")
    with pytest.raises(HTTPException) as error:
        auth.autenticar_credencial(valor)
    assert error.value.status_code == 401
    assert error.value.detail == {
        "code": "TERMINAL_NO_AUTORIZADO",
        "message": "No se pudo autenticar el terminal.",
    }


@pytest.mark.parametrize(
    "fallo", ["ausente", "relativa", "json", "duplicado", "excesivo", "solape"]
)
def test_configuracion_invalida_falla_cerrada(entorno, fallo):
    e = entorno
    if fallo == "ausente":
        e.settings.atm_terminal_credentials_file = ""
    elif fallo == "relativa":
        e.settings.atm_terminal_credentials_file = "registro.json"
    elif fallo == "json":
        e.path.write_text("{", encoding="utf-8")
    elif fallo == "duplicado":
        cuerpo = json.dumps(e.registro)[1:-1]
        e.path.write_text("{" + cuerpo + "," + cuerpo + "}", encoding="utf-8")
    elif fallo == "excesivo":
        e.path.write_bytes(b" " * (auth.MAX_REGISTRY_BYTES + 1))
    else:
        e.registro[secrets.token_urlsafe(12)] = e.registro[e.id].copy()
        e.path.write_text(json.dumps(e.registro), encoding="utf-8")
    with pytest.raises(HTTPException) as error:
        auth.autenticar_credencial(e.credential)
    assert error.value.status_code == 503
    assert e.secret not in str(error.value.detail)


def test_revocacion_se_lee_sin_cache(entorno):
    e = entorno
    terminal = auth.autenticar_credencial(e.credential)
    e.registro[e.id]["enabled"] = False
    e.path.write_text(json.dumps(e.registro), encoding="utf-8")
    with pytest.raises(HTTPException):
        auth.revalidar_terminal(terminal)
    with pytest.raises(HTTPException):
        auth.autenticar_credencial(e.credential)


@pytest.mark.parametrize("cambio", ["codigoATM", "sha256", "auditUserId"])
def test_revalidacion_detecta_cambio_de_asociacion(entorno, cambio):
    e = entorno
    terminal = auth.autenticar_credencial(e.credential)
    e.registro[e.id][cambio] = {
        "codigoATM": "ATM00002",
        "sha256": "0" * 64,
        "auditUserId": 901,
    }[cambio]
    e.path.write_text(json.dumps(e.registro), encoding="utf-8")
    with pytest.raises(HTTPException):
        auth.revalidar_terminal(terminal)


def test_https_no_confia_en_cabecera_forwarded(entorno):
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/atm/auth",
            "scheme": "http",
            "headers": [
                (b"x-forwarded-proto", b"https"),
                (b"x-atm-credential", entorno.credential),
            ],
        }
    )
    with pytest.raises(HTTPException) as error:
        auth.require_terminal(request, None)
    assert error.value.status_code == 403


@pytest.mark.parametrize("valores", [[], [b"a", b"b"], [b"x" * 109]])
def test_cabecera_ausente_duplicada_o_excesiva(valores):
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/atm/auth",
            "scheme": "https",
            "headers": [(b"x-atm-credential", v) for v in valores],
        }
    )
    with pytest.raises(HTTPException) as error:
        auth.require_terminal(request, None)
    assert error.value.status_code == 401


def test_aprovisionamiento_rotacion_y_revocacion_local(tmp_path, monkeypatch, capsys):
    path = tmp_path / "registro.json"
    salida1, salida2 = tmp_path / "entrega1", tmp_path / "entrega2"
    vence = datetime.now(UTC) + timedelta(days=1)
    herramienta.actualizar_registro(
        path, "issue", codigo="ATM00001", usuario=900, vence=vence, entrega=salida1
    )
    credential1 = salida1.read_bytes().strip()
    id1, secret1 = credential1.decode().split(".")
    assert len(base64.urlsafe_b64decode(secret1 + "=")) == 32
    assert secret1 not in path.read_text()
    monkeypatch.setattr(
        auth,
        "get_settings",
        lambda: Settings.model_construct(atm_terminal_credentials_file=str(path)),
    )
    assert auth.autenticar_credencial(credential1)
    herramienta.actualizar_registro(
        path, "rotate", codigo="ATM00001", usuario=900, vence=vence, entrega=salida2
    )
    credential2 = salida2.read_bytes().strip()
    assert credential1 != credential2
    registros = auth.validar_registro(path.read_bytes())
    ventanas = list(registros.values())
    assert min(v.expires_at for v in ventanas) - max(
        v.not_before for v in ventanas
    ) <= timedelta(minutes=15)
    assert auth.autenticar_credencial(credential1)
    assert auth.autenticar_credencial(credential2)
    herramienta.actualizar_registro(path, "revoke", credential_id=id1)
    with pytest.raises(HTTPException):
        auth.autenticar_credencial(credential1)
    assert auth.autenticar_credencial(credential2)
    assert capsys.readouterr().out == ""


def test_herramienta_no_escribe_en_repositorio():
    with pytest.raises(ValueError):
        herramienta.actualizar_registro(
            Path(__file__).resolve().parents[3] / "no-crear.json", "issue"
        )


def test_herramienta_no_sobrescribe_entrega(tmp_path):
    path, entrega = tmp_path / "registro.json", tmp_path / "entrega"
    entrega.write_text("existente")
    with pytest.raises(FileExistsError):
        herramienta.actualizar_registro(
            path,
            "issue",
            codigo="ATM00001",
            usuario=900,
            vence=datetime.now(UTC) + timedelta(days=1),
            entrega=entrega,
        )
    assert entrega.read_text() == "existente"
    assert not path.exists()
