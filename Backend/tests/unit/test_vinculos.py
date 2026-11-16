"""Vínculos de productos y subproductos (/api/v1/productos/.../vinculos), sin BD."""

from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.database.db import cooperativa
from app.core.security import audit
from app.modules.productos import repository as repo
from app.modules.productos import vinculos
from app.modules.productos.router import router
from tests.sesion import simular_sesion, usuario_con_roles

BASE = "https://testserver/api/v1/productos"
EVENTOS: list[audit.EventoAuditoria] = []

PRODUCTOS = {
    1: {"id_producto": 1, "tipo_producto": "Tarjeta", "id_tipo_credito": None},
    2: {"id_producto": 2, "tipo_producto": "Credito", "id_tipo_credito": 1},
}
SUBPRODUCTOS = {10: {"id_sub_producto": 10, "id_producto": 1}}
TASAS = {
    5: {"id": 5, "tipo": "TARJETA_COMPRA", "tipo_credito": None},
    6: {"id": 6, "tipo": "AHORRO", "tipo_credito": None},
    7: {"id": 7, "tipo": "CREDITO", "tipo_credito": 1},
    8: {"id": 8, "tipo": "CREDITO", "tipo_credito": 2},
}


@pytest.fixture
def bd(monkeypatch: pytest.MonkeyPatch) -> dict[tuple[str, int], dict[str, Any]]:
    guardado: dict[tuple[str, int], dict[str, Any]] = {}
    vacio = {
        "tasas_interes": [],
        "comisiones": [],
        "seguros": [],
        "sistemas_amortizacion": [],
    }

    def filas(_c: Any, sql: str, ids: list[int]) -> list[dict[str, Any]]:
        if "TasaInteres" in sql:
            return [TASAS[i] for i in ids if i in TASAS]
        return [{"id": i} for i in ids if i in (1, 2)]  # comisiones y seguros 1 y 2

    def guardar(
        _c: Any, destino: str, id_: int, datos: Any, _u: int, _t: list[str]
    ) -> None:
        guardado[(destino, id_)] = datos.model_dump()

    monkeypatch.setattr(vinculos, "_filas", filas)
    monkeypatch.setattr(vinculos, "_guardar", guardar)
    monkeypatch.setattr(vinculos, "leer", lambda _c, d, i: guardado.get((d, i), vacio))
    monkeypatch.setattr(repo, "obtener_producto", lambda _c, i, **_k: PRODUCTOS.get(i))
    monkeypatch.setattr(
        repo, "obtener_subproducto", lambda _c, i, **_k: SUBPRODUCTOS.get(i)
    )
    monkeypatch.setattr(audit, "registrar", EVENTOS.append)
    EVENTOS.clear()
    return guardado


def _cliente(*roles: str) -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    conn = MagicMock()
    conn.execute.return_value.scalars.return_value = ["FRANCES", "ALEMAN"]
    app.dependency_overrides[cooperativa] = lambda: conn
    simular_sesion(app, usuario_con_roles(*roles))
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def admin() -> Iterator[TestClient]:
    yield _cliente("ADMIN")


def test_producto_aplica_a_sus_subproductos_y_el_subproducto_se_exonera(bd, admin):
    r = admin.put(
        f"{BASE}/1/vinculos",
        json={"tasasInteres": [5], "comisiones": [{"idComision": 1}]},
    )
    assert r.status_code == 200, r.text
    r = admin.put(
        f"{BASE}/subproductos/10/vinculos",
        json={"comisiones": [{"idComision": 1, "exonerado": True}]},
    )
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["comisiones"] == [{"idComision": 1, "exonerado": True}]
    assert cuerpo["delProducto"]["tasasInteres"] == [5]


def test_asesor_consulta_y_no_cambia(bd):
    asesor = _cliente("ASESOR")
    assert asesor.get(f"{BASE}/1/vinculos").status_code == 200
    assert asesor.put(f"{BASE}/1/vinculos", json={}).status_code == 403
    assert bd == {}


@pytest.mark.parametrize(
    ("url", "cuerpo", "codigo"),
    [
        ("1/vinculos", {"tasasInteres": [6]}, "TASA_NO_APLICA"),  # ahorro en tarjeta
        ("2/vinculos", {"tasasInteres": [8]}, "TASA_NO_APLICA"),  # otro tipo de crédito
        ("1/vinculos", {"tasasInteres": [99]}, "TASA_NO_APLICA"),
        ("1/vinculos", {"comisiones": [{"idComision": 9}]}, "COMISION_NO_EXISTE"),
        (
            "1/vinculos",
            {"comisiones": [{"idComision": 1, "exonerado": True}]},
            "CAMPO_NO_APLICA",
        ),
        ("1/vinculos", {"seguros": [{"idSeguro": 9}]}, "SEGURO_NO_EXISTE"),
        ("1/vinculos", {"sistemasAmortizacion": ["FRANCES"]}, "CAMPO_NO_APLICA"),
    ],
)
def test_reglas(bd, admin, url, cuerpo, codigo):
    r = admin.put(f"{BASE}/{url}", json=cuerpo)
    assert r.status_code == 422 and r.json()["code"] == codigo, r.text
    assert bd == {}


def test_credito_vincula_sus_tasas_y_amortizacion(bd, admin):
    r = admin.put(
        f"{BASE}/2/vinculos",
        json={
            "tasasInteres": [7],
            "sistemasAmortizacion": ["frances"],
            "seguros": [{"idSeguro": 1, "esObligatorio": True}],
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["sistemasAmortizacion"] == ["FRANCES"]


def test_repetidos_e_inexistentes(bd, admin):
    assert admin.put(
        f"{BASE}/1/vinculos", json={"tasasInteres": [5, 5]}
    ).status_code in (400, 422)
    assert admin.put(f"{BASE}/99/vinculos", json={}).status_code == 404
    assert admin.get(f"{BASE}/subproductos/99/vinculos").status_code == 404


def test_auditoria_por_tabla_que_cambia(bd, admin):
    admin.put(
        f"{BASE}/1/vinculos",
        json={"tasasInteres": [5], "comisiones": [{"idComision": 1}]},
    )
    tablas = sorted(e.tabla or "" for e in EVENTOS)
    assert tablas == [
        "ProductosFinancieros.ProductoComision",
        "ProductosFinancieros.ProductoTasaInteres",
    ]
    assert all(e.resultado == "Exitoso" for e in EVENTOS)
    EVENTOS.clear()
    # Sin cambios: no escribe ni audita
    admin.put(
        f"{BASE}/1/vinculos",
        json={"tasasInteres": [5], "comisiones": [{"idComision": 1}]},
    )
    assert EVENTOS == []
    # Solo cambia una lista: un solo registro, con lo que se desmarcó
    admin.put(f"{BASE}/1/vinculos", json={"tasasInteres": [5]})
    assert [e.tabla for e in EVENTOS] == ["ProductosFinancieros.ProductoComision"]
    assert "desmarcados=1" in EVENTOS[0].descripcion


def test_auditoria_del_fallo_en_la_tabla_afectada(bd, admin):
    r = admin.put(f"{BASE}/1/vinculos", json={"seguros": [{"idSeguro": 9}]})
    assert r.status_code == 422
    assert [(e.tabla, e.resultado) for e in EVENTOS] == [
        ("ProductosFinancieros.ProductoSeguro", "Fallido")
    ]
