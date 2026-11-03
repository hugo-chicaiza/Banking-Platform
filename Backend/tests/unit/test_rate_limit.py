"""Límite de peticiones, con reloj simulado."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.api.rate_limit import ContadorPeticiones, LimitePeticionesMiddleware
from app.core.config.settings import Settings


class _Reloj:
    def __init__(self) -> None:
        self.ahora = 1000.0

    def __call__(self) -> float:
        return self.ahora


@pytest.fixture()
def reloj():
    return _Reloj()


def _cliente(reloj, ip="8.8.8.8", contador=None):
    app = FastAPI()
    app.add_middleware(
        LimitePeticionesMiddleware,
        lectura=3,
        escritura=2,
        sensible=1,
        contador_peticiones=contador or ContadorPeticiones(reloj=reloj),
    )

    @app.get("/api/v1/x")
    def leer() -> dict[str, str]:
        return {"ok": "si"}

    @app.post("/api/v1/x")
    def escribir() -> dict[str, str]:
        return {"ok": "si"}

    @app.post("/api/v1/tarjetas/1/pin")
    def pin() -> dict[str, str]:
        return {"ok": "si"}

    @app.get("/libre")
    def libre() -> dict[str, str]:
        return {"ok": "si"}

    return TestClient(app, client=(ip, 5000))


def test_lectura_excede_429_con_retry_after(reloj):
    c = _cliente(reloj)

    assert [c.get("/api/v1/x").status_code for _ in range(3)] == [200, 200, 200]
    r = c.get("/api/v1/x")

    assert r.status_code == 429
    assert r.json()["code"] == "DEMASIADAS_SOLICITUDES"
    assert r.headers["retry-after"] == "60"
    assert r.headers["content-type"].startswith("application/problem+json")


def test_ventana_deslizante_libera_solo_lo_vencido(reloj):
    c = _cliente(reloj)
    c.get("/api/v1/x")
    reloj.ahora += 30
    c.get("/api/v1/x")
    c.get("/api/v1/x")
    assert c.get("/api/v1/x").status_code == 429

    reloj.ahora += 31  # solo venció la primera
    assert c.get("/api/v1/x").status_code == 200
    assert c.get("/api/v1/x").status_code == 429


def test_peticiones_rechazadas_no_alargan_el_bloqueo(reloj):
    c = _cliente(reloj)
    for _ in range(3):
        c.get("/api/v1/x")
    for _ in range(20):
        assert c.get("/api/v1/x").status_code == 429

    reloj.ahora += 60

    assert c.get("/api/v1/x").status_code == 200


def test_cada_clase_tiene_su_propio_limite(reloj):
    c = _cliente(reloj)

    assert c.post("/api/v1/tarjetas/1/pin").status_code == 200
    assert c.post("/api/v1/tarjetas/1/pin").status_code == 429
    assert c.post("/api/v1/x").status_code == 200
    assert c.post("/api/v1/x").status_code == 200
    assert c.post("/api/v1/x").status_code == 429
    assert c.get("/api/v1/x").status_code == 200


def test_cada_ip_cuenta_por_separado(reloj):
    contador = ContadorPeticiones(reloj=reloj)
    a = _cliente(reloj, "8.8.8.8", contador)
    b = _cliente(reloj, "1.1.1.1", contador)

    assert a.post("/api/v1/tarjetas/1/pin").status_code == 200
    assert a.post("/api/v1/tarjetas/1/pin").status_code == 429
    assert b.post("/api/v1/tarjetas/1/pin").status_code == 200


def test_rutas_fuera_de_api_no_se_limitan(reloj):
    c = _cliente(reloj)

    assert {c.get("/libre").status_code for _ in range(10)} == {200}


def test_memoria_acotada_descarta_la_clave_mas_antigua(reloj):
    contador = ContadorPeticiones(max_claves=2, reloj=reloj)

    assert contador.registrar(("a", "lectura"), 1) is None
    assert contador.registrar(("b", "lectura"), 1) is None
    assert (
        contador.registrar(("a", "lectura"), 1) is not None
    )  # "a" pasa a ser reciente
    assert contador.registrar(("c", "lectura"), 1) is None

    assert contador.registrar(("a", "lectura"), 1) is not None
    assert contador.registrar(("b", "lectura"), 1) is None  # "b" fue descartada


def test_limite_activo_por_defecto():
    assert Settings.model_fields["limite_peticiones_activo"].default is True


def test_app_real_limita_el_pin_a_cinco_por_minuto():
    from app.main import app

    c = TestClient(app, client=("8.8.4.4", 5000))
    codigos = [
        c.post("/api/v1/tarjetas/1/pin", json={"pin": "x"}).status_code
        for _ in range(6)
    ]

    assert 429 not in codigos[:5]
    assert codigos[5] == 429
