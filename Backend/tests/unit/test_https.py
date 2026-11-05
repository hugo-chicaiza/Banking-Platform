"""Solo HTTPS: URLs de redirección del login y cabecera HSTS."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.api.middleware import HSTS, HstsMiddleware
from app.core.config.settings import Settings


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
