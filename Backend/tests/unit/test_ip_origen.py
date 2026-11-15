"""ASVS 4.1.3 / 15.3.4: la IP del usuario solo la fija el Worker con el secreto compartido."""

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import SecretStr

from app.core.api import middleware
from app.core.api.middleware import SoloProxyMiddleware, ip_cliente, viene_del_proxy

SECRETO = "s3cr3to-del-worker"


@pytest.fixture
def con_secreto(monkeypatch):
    monkeypatch.setattr(
        middleware,
        "get_settings",
        lambda: SimpleNamespace(proxy_secreto=SecretStr(SECRETO)),
    )


@pytest.fixture
def sin_secreto(monkeypatch):
    monkeypatch.setattr(
        middleware, "get_settings", lambda: SimpleNamespace(proxy_secreto=SecretStr(""))
    )


def _scope(
    *cabeceras: tuple[bytes, bytes], cliente: str = "10.0.0.5"
) -> dict[str, Any]:
    return {"type": "http", "client": (cliente, 443), "headers": list(cabeceras)}


def test_worker_con_secreto_fija_la_ip(con_secreto):
    scope = _scope(
        (b"x-proxy-secreto", SECRETO.encode()), (b"x-cliente-ip", b"203.0.113.7")
    )
    assert viene_del_proxy(scope)
    assert ip_cliente(scope) == "203.0.113.7"


def test_ipv6_del_worker(con_secreto):
    scope = _scope(
        (b"x-proxy-secreto", SECRETO.encode()), (b"x-cliente-ip", b"2001:db8::1")
    )
    assert ip_cliente(scope) == "2001:db8::1"


@pytest.mark.parametrize(
    "cabeceras",
    [
        # sin secreto: un cliente directo no puede elegir su IP
        [(b"x-cliente-ip", b"203.0.113.7")],
        # secreto equivocado
        [(b"x-proxy-secreto", b"otro"), (b"x-cliente-ip", b"203.0.113.7")],
        # secreto repetido: ambiguo, no se acepta
        [
            (b"x-proxy-secreto", SECRETO.encode()),
            (b"x-proxy-secreto", SECRETO.encode()),
            (b"x-cliente-ip", b"203.0.113.7"),
        ],
        # X-Forwarded-For nunca se lee
        [(b"x-forwarded-for", b"203.0.113.7")],
    ],
)
def test_sin_secreto_valido_se_usa_la_conexion(con_secreto, cabeceras):
    assert ip_cliente(_scope(*cabeceras)) == "10.0.0.5"


@pytest.mark.parametrize("valor", [b"no-es-ip", b"203.0.113.7, 198.51.100.1", b""])
def test_ip_invalida_del_worker_cae_a_la_conexion(con_secreto, valor):
    scope = _scope((b"x-proxy-secreto", SECRETO.encode()), (b"x-cliente-ip", valor))
    assert ip_cliente(scope) == "10.0.0.5"


def test_dos_cabeceras_de_ip_no_se_aceptan(con_secreto):
    scope = _scope(
        (b"x-proxy-secreto", SECRETO.encode()),
        (b"x-cliente-ip", b"203.0.113.7"),
        (b"x-cliente-ip", b"198.51.100.1"),
    )
    assert ip_cliente(scope) == "10.0.0.5"


def test_sin_secreto_configurado_nunca_es_proxy(sin_secreto):
    scope = _scope((b"x-proxy-secreto", b""), (b"x-cliente-ip", b"203.0.113.7"))
    assert not viene_del_proxy(scope)
    assert ip_cliente(scope) == "10.0.0.5"


def test_conexion_sin_ip_valida(sin_secreto):
    assert ip_cliente({"type": "http", "headers": []}) == "desconocida"


def _llamar(scope: dict[str, Any]) -> tuple[int, bytes]:
    enviados: list[dict[str, Any]] = []

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    async def receive():
        return {"type": "http.request"}

    async def send(mensaje):
        enviados.append(mensaje)

    asyncio.run(SoloProxyMiddleware(app)(scope, receive, send))
    return enviados[0]["status"], enviados[1]["body"]


def test_solo_proxy_rechaza_trafico_directo(con_secreto):
    status, cuerpo = _llamar(_scope((b"x-cliente-ip", b"203.0.113.7")))
    assert status == 403
    assert b"ORIGEN_NO_PERMITIDO" in cuerpo


def test_solo_proxy_deja_pasar_al_worker(con_secreto):
    status, cuerpo = _llamar(_scope((b"x-proxy-secreto", SECRETO.encode())))
    assert (status, cuerpo) == (200, b"ok")
