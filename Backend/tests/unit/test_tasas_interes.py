"""Catálogo de tasas de interés y sistemas de amortización (/api/v1/catalogos), sin BD."""

from datetime import date
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.database.db import cooperativa
from app.core.security import audit
from app.modules.catalogos import repository, service
from app.modules.catalogos.router import router
from tests.sesion import simular_sesion, usuario_con_roles

BASE = "https://testserver/api/v1/catalogos"
HOY = date(2026, 11, 15)
NUEVA = {
    "idTipoCredito": 1,
    "tasaNominalAnual": 0.15,
    "plazoMaximoMeses": 60,
    "montoMinimo": 20000.01,
    "montoMaximo": 40000,
    "vigenciaDesde": "2026-12-01",
}


def _fila(**cambios: Any) -> dict[str, Any]:
    return {
        "id_tasa_interes": 1,
        "tipo_tasa": "CREDITO",
        "id_tipo_credito": 1,
        "nombre_tipo_credito": "Crédito de consumo",
        "tasa_nominal_anual": Decimal("0.1600"),
        "recargo_mora_sobre_tasa": Decimal("0.0200"),
        "plazo_maximo_meses": 48,
        "monto_minimo": Decimal("500.00"),
        "monto_maximo": Decimal("20000.00"),
        "vigencia_desde": date(2026, 1, 1),
        "vigencia_hasta": None,
        "vigente": True,
    } | cambios


@pytest.fixture
def bd(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    insertadas: list[dict[str, Any]] = []
    monkeypatch.setattr(service, "hoy", lambda: HOY)
    monkeypatch.setattr(
        repository, "listar_tasas_interes", lambda _c, _h, _t, _tt: [_fila()]
    )
    monkeypatch.setattr(repository, "existe_tipo_credito_activo", lambda _c, t: t == 1)
    monkeypatch.setattr(
        repository,
        "tasas_que_se_solapan",
        lambda _c, d: [1] if (d["monto_minimo"] or 0) <= 20000 else [],
    )
    monkeypatch.setattr(
        repository, "insertar_tasa_interes", lambda _c, d: insertadas.append(d) or 7
    )
    monkeypatch.setattr(
        repository,
        "obtener_tasa_interes",
        lambda _c, i, _h: _fila(id_tasa_interes=i, vigente=False),
    )
    monkeypatch.setattr(
        repository,
        "listar_sistemas_amortizacion",
        lambda _c: [
            {"codigo": "FRANCES", "nombre": "Francés", "descripcion": "Cuota fija"}
        ],
    )
    monkeypatch.setattr(audit, "registrar", lambda _e: None)
    return insertadas


def _cliente(*roles: str) -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[cooperativa] = lambda: MagicMock()
    simular_sesion(app, usuario_con_roles(*roles))
    return TestClient(app, raise_server_exceptions=False)


def test_listar_tasas_y_sistemas(bd):
    cliente = _cliente("ASESOR")
    r = cliente.get(f"{BASE}/tasas-interes?idTipoCredito=1")
    assert r.status_code == 200
    assert r.json()[0]["tasaNominalAnual"] == 0.16 and r.json()[0]["vigente"] is True
    assert cliente.get(f"{BASE}/sistemas-amortizacion").json()[0]["codigo"] == "FRANCES"
    assert cliente.get(f"{BASE}/tasas-interes?otro=1").status_code == 400


def test_solo_admin_crea_tasa(bd):
    assert (
        _cliente("ASESOR").post(f"{BASE}/tasas-interes", json=NUEVA).status_code == 403
    )
    r = _cliente("ADMIN").post(f"{BASE}/tasas-interes", json=NUEVA)
    assert r.status_code == 201, r.text
    assert r.json()["idTasaInteres"] == 7 and bd[0]["monto_maximo"] == Decimal(40000)


@pytest.mark.parametrize(
    ("cambio", "status", "codigo"),
    [
        ({"montoMinimo": 1000}, 409, "TASA_SOLAPADA"),
        ({"vigenciaDesde": "2026-11-01"}, 422, "VIGENCIA_PASADA"),
        ({"idTipoCredito": 9}, 422, "TIPO_CREDITO_NO_EXISTE"),
    ],
)
def test_reglas_de_la_tasa(bd, cambio, status, codigo):
    r = _cliente("ADMIN").post(f"{BASE}/tasas-interes", json={**NUEVA, **cambio})
    assert r.status_code == status and r.json()["code"] == codigo
    assert bd == []


@pytest.mark.parametrize(
    "cambio",
    [
        {"tasaNominalAnual": 1.5},
        {"tasaNominalAnual": 0},
        {"montoMaximo": 100},
        {"vigenciaHasta": "2026-11-30"},
        {"plazoMaximoMeses": 0},
    ],
)
def test_tasa_fuera_de_rango(bd, cambio):
    r = _cliente("ADMIN").post(f"{BASE}/tasas-interes", json={**NUEVA, **cambio})
    assert r.status_code in (400, 422)
