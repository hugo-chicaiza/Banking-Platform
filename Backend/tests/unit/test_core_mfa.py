"""core/security/mfa: el código MFA solo autoriza la acción y el recurso que lo pidieron."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from pydantic import SecretStr
from workos.exceptions import BadRequestException

from app.core.config.settings import get_settings
from app.core.security import mfa
from tests.sesion import USUARIO

ACCION = "clientes.revelar"
RECURSO = "cliente:10|campos:email"


class _WorkOS:
    def __init__(
        self, factores=("auth_factor_1",), valido=True, factor_reto="auth_factor_1"
    ):
        self.factores = factores
        self.valido = valido
        self.factor_reto = factor_reto
        self.verificaciones = 0
        self.user_management = SimpleNamespace(list_auth_factors=self._listar)
        self.mfa = SimpleNamespace(
            challenge_factor=self._retar, verify_challenge=self._verificar
        )

    def _listar(self, *, user_id):
        return [SimpleNamespace(id=f, type="totp") for f in self.factores]

    def _retar(self, *, authentication_factor_id):
        return SimpleNamespace(id="auth_challenge_1", code="999999", expires_at=None)

    def _verificar(self, *, authentication_challenge_id, code):
        self.verificaciones += 1
        if self.valido is None:
            raise BadRequestException(MagicMock(status_code=400), {"message": "usado"})
        return SimpleNamespace(
            valid=self.valido,
            challenge=SimpleNamespace(authentication_factor_id=self.factor_reto),
        )


@pytest.fixture
def workos(monkeypatch):
    monkeypatch.setattr(get_settings(), "workos_cookie_password", SecretStr("x" * 40))

    def instalar(**kw):
        falso = _WorkOS(**kw)
        monkeypatch.setattr(mfa, "get_workos", lambda: falso)
        return falso

    return instalar


def test_desafio_no_entrega_el_codigo_y_trae_comprobante(workos):
    workos()
    desafio = mfa.pedir_desafio(USUARIO, ACCION, RECURSO)
    assert desafio.id_desafio == "auth_challenge_1"
    assert "999999" not in desafio.comprobante
    assert desafio.comprobante.split(".")[0].isdigit()


def test_mismo_contexto_verifica(workos):
    falso = workos()
    d = mfa.pedir_desafio(USUARIO, ACCION, RECURSO)
    assert mfa.verificar(
        USUARIO, ACCION, RECURSO, d.id_desafio, d.comprobante, "123456"
    )
    assert falso.verificaciones == 1


@pytest.mark.parametrize(
    ("usuario", "accion", "recurso"),
    [
        (USUARIO, "creditos.aprobar", RECURSO),  # otra acción
        (USUARIO, ACCION, "cliente:11|campos:email"),  # otro cliente
        (USUARIO, ACCION, "cliente:10|campos:email,identificacion"),  # otros campos
        (replace(USUARIO, id_sesion="otra_sesion"), ACCION, RECURSO),  # otra sesión
        (replace(USUARIO, id_usuario="user_otro"), ACCION, RECURSO),  # otro usuario
    ],
)
def test_no_sirve_para_otra_accion_recurso_sesion_o_usuario(
    workos, usuario, accion, recurso
):
    falso = workos()
    d = mfa.pedir_desafio(USUARIO, ACCION, RECURSO)
    assert not mfa.verificar(
        usuario, accion, recurso, d.id_desafio, d.comprobante, "123456"
    )
    assert falso.verificaciones == 0  # se rechaza antes de consultar a WorkOS


def test_comprobante_de_otro_desafio_no_sirve(workos):
    workos()
    d = mfa.pedir_desafio(USUARIO, ACCION, RECURSO)
    assert not mfa.verificar(
        USUARIO, ACCION, RECURSO, "auth_challenge_2", d.comprobante, "123456"
    )


@pytest.mark.parametrize(
    "comprobante",
    ["", "sin-punto", "abc.def", "123.", "9999999999.AAAAAAAAAAAAAAAAAAAAAAAAAAA"],
)
def test_comprobante_alterado_o_mal_formado(workos, comprobante):
    workos()
    assert not mfa.verificar(
        USUARIO, ACCION, RECURSO, "auth_challenge_1", comprobante, "123456"
    )


def test_comprobante_vencido(workos, monkeypatch):
    workos()
    d = mfa.pedir_desafio(USUARIO, ACCION, RECURSO)
    reloj = mfa.time.time() + mfa.VIGENCIA_SEGUNDOS + 1
    monkeypatch.setattr(mfa.time, "time", lambda: reloj)
    assert not mfa.verificar(
        USUARIO, ACCION, RECURSO, d.id_desafio, d.comprobante, "123456"
    )


@pytest.mark.parametrize(
    "caso",
    [{"valido": False}, {"valido": None}, {"factor_reto": "auth_factor_ajeno"}],
)
def test_codigo_invalido_usado_o_de_otro_factor(workos, caso):
    workos(**caso)
    d = mfa.pedir_desafio(USUARIO, ACCION, RECURSO)
    assert not mfa.verificar(
        USUARIO, ACCION, RECURSO, d.id_desafio, d.comprobante, "123456"
    )


@pytest.mark.parametrize("faltante", ["id_desafio", "comprobante", "codigo"])
def test_sin_datos_no_verifica(workos, faltante):
    workos()
    datos: dict[str, str | None] = {
        "id_desafio": "auth_challenge_1",
        "comprobante": "1.x",
        "codigo": "123456",
    }
    datos[faltante] = None
    assert not mfa.verificar(USUARIO, ACCION, RECURSO, **datos)


def test_sin_factor_es_409(workos):
    workos(factores=())
    with pytest.raises(HTTPException) as exc:
        mfa.pedir_desafio(USUARIO, ACCION, RECURSO)
    assert exc.value.status_code == 409


def test_sin_secreto_falla_cerrado(workos, monkeypatch):
    workos()
    monkeypatch.setattr(get_settings(), "workos_cookie_password", SecretStr(""))
    with pytest.raises(HTTPException) as exc:
        mfa.pedir_desafio(USUARIO, ACCION, RECURSO)
    assert exc.value.status_code == 503
