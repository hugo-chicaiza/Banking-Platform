"""Solo HTTPS: URLs de redirección del login y cabecera HSTS."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.api.middleware import HSTS, HstsMiddleware
from app.core.config.settings import Settings


@pytest.fixture(autouse=True)
def _sin_env_local(monkeypatch, tmp_path):
    """Settings lee .env de la carpeta actual: sin esto, el .env del dev cambia el resultado."""
    monkeypatch.chdir(tmp_path)
    for variable in ("FRONTEND_URL", "WORKOS_REDIRECT_URI"):
        monkeypatch.delenv(variable, raising=False)


@pytest.mark.parametrize(
    "url",
    ["https://banca.ejemplo.ec", "http://localhost:5173", "http://127.0.0.1:5173"],
)
def test_frontend_url_acepta_https_y_localhost(url):
    assert Settings(frontend_url=url).frontend_url == url


@pytest.mark.parametrize(
    "url", ["http://banca.ejemplo.ec", "http://10.0.0.5:5173", "ftp://banca.ejemplo.ec"]
)
def test_frontend_url_rechaza_http_fuera_de_localhost(url):
    with pytest.raises(ValueError, match="FRONTEND_URL"):
        Settings(frontend_url=url)


@pytest.mark.parametrize(
    "url",
    [
        "https://banca.ejemplo.ec/api/v1/auth/callback",
        "http://localhost:5173/api/v1/auth/callback",
    ],
)
def test_redirect_uri_acepta_https_y_localhost(url):
    assert Settings(workos_redirect_uri=url).workos_redirect_uri == url


@pytest.mark.parametrize(
    "url", ["http://banca.ejemplo.ec/api/v1/auth/callback", "/api/v1/auth/callback"]
)
def test_redirect_uri_rechaza_http_y_rutas_relativas(url):
    with pytest.raises(ValueError, match="WORKOS_REDIRECT_URI"):
        Settings(workos_redirect_uri=url)


def test_hsts_en_cada_respuesta_incluidos_errores():
    app = FastAPI()

    @app.get("/ok")
    def ok() -> dict[str, str]:
        return {"ok": "si"}

    app.add_middleware(HstsMiddleware)
    client = TestClient(app)

    assert client.get("/ok").headers["strict-transport-security"] == HSTS
    assert client.get("/no-existe").headers["strict-transport-security"] == HSTS


def test_frontend_url_admite_varios_origenes():
    s = Settings(frontend_url="http://localhost:5173, http://localhost:8471/")

    assert s.origenes_frontend == ("http://localhost:5173", "http://localhost:8471")


@pytest.mark.parametrize(
    ("valor", "mensaje"),
    [
        ("http://localhost:5173,http://banca.ejemplo.ec", "https://"),
        ("http://localhost:5173,http://LOCALHOST:5173", "repite"),
        ("http://localhost:5173,localhost:8471", "esquema"),
    ],
)
def test_frontend_url_rechaza_listas_invalidas(valor, mensaje):
    with pytest.raises(ValueError, match=mensaje):
        Settings(frontend_url=valor)


def test_callback_fijo_solo_con_un_origen():
    with pytest.raises(ValueError, match="WORKOS_REDIRECT_URI vacío"):
        Settings(
            frontend_url="http://localhost:5173,http://localhost:8471",
            workos_redirect_uri="http://localhost:5173/api/v1/auth/callback",
        )
