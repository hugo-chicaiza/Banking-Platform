"""FRONTEND_ORIGIN_REGEX: origen del FE desde previews de PR de Cloudflare (backend-dev).

resolver_origen_front y la validación de la regex al arrancar. El login, callback,
logout y CSRF desde una preview están en test_auth.py.
"""

import logging

import pytest
from fastapi import Request

from app.core.config.settings import Settings, get_settings
from app.core.security.origen import resolver_origen_front

FRONT_DEV = "https://banking-platform-front.diegosebastia94.workers.dev"
PREVIEW_HOST = "pr-12-banking-platform-front.diegosebastia94.workers.dev"
REGEX = r"^https://[a-z0-9-]+-banking-platform-front\.diegosebastia94\.workers\.dev$"


@pytest.fixture()
def configurar(monkeypatch):
    def aplicar(regex: str = REGEX) -> None:
        monkeypatch.setenv("FRONTEND_URL", FRONT_DEV)
        monkeypatch.setenv("WORKOS_API_KEY", "sk_test_prueba")
        monkeypatch.setenv("FRONTEND_ORIGIN_REGEX", regex)
        get_settings.cache_clear()

    yield aplicar
    get_settings.cache_clear()


def _peticion(*hosts: str) -> Request:
    cabeceras = [(b"x-forwarded-host", host.encode("latin-1")) for host in hosts]
    return Request({"type": "http", "method": "GET", "headers": cabeceras})


# --- resolver_origen_front ---------------------------------------------------------


def test_preview_valida_es_el_origen(configurar):
    configurar()

    assert resolver_origen_front(_peticion(PREVIEW_HOST)) == f"https://{PREVIEW_HOST}"


def test_host_de_develop_devuelve_frontend_url(configurar):
    configurar()

    assert resolver_origen_front(_peticion(FRONT_DEV.removeprefix("https://"))) == (
        FRONT_DEV
    )


def test_mayusculas_se_normalizan(configurar):
    configurar()

    origen = resolver_origen_front(_peticion(PREVIEW_HOST.upper()))

    assert origen == f"https://{PREVIEW_HOST}"


def test_sin_regex_se_ignora_la_cabecera(configurar):
    configurar(regex="")

    assert resolver_origen_front(_peticion(PREVIEW_HOST)) == FRONT_DEV


def test_sin_cabecera_devuelve_frontend_url(configurar):
    configurar()

    assert resolver_origen_front(_peticion()) == FRONT_DEV


@pytest.mark.parametrize(
    "host",
    [
        "",
        f"{PREVIEW_HOST}:443",
        f"{PREVIEW_HOST},evil.com",
        f"evil.com,{PREVIEW_HOST}",
        f"usuario@{PREVIEW_HOST}",
        f"{PREVIEW_HOST}/ruta",
        f" {PREVIEW_HOST}",
        f"{PREVIEW_HOST}\n",  # con re.match y ^...$ pasaría; con fullmatch no
        "pr-12-bañking-platform-front.diegosebastia94.workers.dev",
        "a" * 254,
        "evil.com",
        "x.workers.dev.evil.com",
        "banking-platform-front.diegosebastia94.workers.dev.evil.com",
        f"{PREVIEW_HOST}.evil.com",
        "pr-12-banking-platform-front.otra-cuenta.workers.dev",
    ],
)
def test_host_invalido_devuelve_frontend_url(configurar, host):
    configurar()

    assert resolver_origen_front(_peticion(host)) == FRONT_DEV


def test_dos_cabeceras_devuelven_frontend_url(configurar):
    configurar()

    origen = resolver_origen_front(_peticion(PREVIEW_HOST, PREVIEW_HOST))

    assert origen == FRONT_DEV


def test_logs_de_depuracion_sin_volcar_valores_invalidos(configurar, caplog):
    configurar()
    caplog.set_level(logging.DEBUG, logger="app.core.security.origen")

    resolver_origen_front(_peticion(PREVIEW_HOST))
    resolver_origen_front(_peticion(PREVIEW_HOST, PREVIEW_HOST))
    resolver_origen_front(_peticion(f"{PREVIEW_HOST},otro.com"))
    resolver_origen_front(_peticion("usuario@secreto.com"))

    texto = caplog.text
    assert f"origen: preview origen=https://{PREVIEW_HOST}" in texto
    assert "2 cabeceras X-Forwarded-Host" in texto
    assert "2 valores separados por coma" in texto
    assert "secreto" not in texto and "otro.com" not in texto


# --- Validación al arrancar --------------------------------------------------------


def _settings(**cambios: str) -> Settings:
    datos = {
        "frontend_url": FRONT_DEV,
        "workos_api_key": "sk_test_prueba",
        "frontend_origin_regex": REGEX,
        **cambios,
    }
    return Settings(_env_file=None, **datos)  # type: ignore[arg-type]


def test_regex_valida_arranca():
    assert _settings().frontend_origin_regex == REGEX


def test_sin_regex_no_exige_clave_de_staging():
    ajustes = _settings(frontend_origin_regex="", workos_api_key="sk_live_x")

    assert ajustes.frontend_origin_regex == ""


@pytest.mark.parametrize("clave", ["sk_live_secreta", "", "sk_secreta"])
def test_regex_exige_clave_de_staging(clave):
    with pytest.raises(ValueError, match="Staging") as error:
        _settings(workos_api_key=clave)

    assert "secreta" not in str(error.value)


@pytest.mark.parametrize(
    ("regex", "mensaje"),
    [
        (r"https://[a-z0-9-]+\.diegosebastia94\.workers\.dev$", "empezar"),
        (r"^http://[a-z0-9-]+\.diegosebastia94\.workers\.dev$", "empezar"),
        (r"^https?://[a-z0-9-]+\.diegosebastia94\.workers\.dev$", "empezar"),
        (r"^https://[a-z0-9-]+\.diegosebastia94\.workers\.dev", "terminar en \\$"),
        (r"^https://([a-z\.diegosebastia94\.workers\.dev$", "regex válida"),
        (r"^https://.*$", "dominio de FRONTEND_URL"),
        (r"^https://[a-z0-9-]+\.workers\.dev$", "dominio de FRONTEND_URL"),
        (
            r"^https://evil\.com$|^https://[a-z0-9-]+\.diegosebastia94\.workers\.dev$",
            "fuera de FRONTEND_URL",
        ),
    ],
)
def test_regex_mal_formada_no_arranca(regex, mensaje):
    with pytest.raises(ValueError, match=mensaje):
        _settings(frontend_origin_regex=regex)


def test_regex_exige_frontend_url_con_dominio():
    with pytest.raises(ValueError, match="dominio propio"):
        _settings(frontend_url="http://localhost:5173")
