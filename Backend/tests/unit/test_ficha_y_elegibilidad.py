"""Ficha del subproducto y productos elegibles para un cliente (E3-02 #375), sin BD."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.database.db import cooperativa
from app.modules.catalogos import repository as catalogos_repo
from app.modules.catalogos import service as catalogos_service
from app.modules.catalogos.router import router as catalogos_router
from app.modules.productos import repository as repo
from app.modules.productos import vinculos
from app.modules.productos.router import router as productos_router
from tests.sesion import simular_sesion, usuario_con_roles

PRODUCTO = {
    "id_producto": 1,
    "codigo_producto": "TAR001",
    "nombre_producto": "Tarjeta Mastercard",
    "descripcion": None,
    "tipo_producto": "Tarjeta",
    "tipo_cuenta": None,
    "monto_apertura_minimo": None,
    "id_tipo_credito": None,
    "nombre_tipo_credito": None,
    "id_red": 2,
    "nombre_red": "Mastercard",
    "permite_operaciones_presenciales": True,
    "estado": "A",
}
SUB = {
    "id_sub_producto": 10,
    "id_producto": 1,
    "codigo_sub_producto": "TCR001-MC",
    "nombre_sub_producto": "Crédito clásica",
    "estado": "A",
    "fecha_registro": datetime(2026, 11, 15),
    "edad_minima": 18,
    "edad_maxima": None,
}


def _cliente(router: Any) -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[cooperativa] = lambda: MagicMock()
    simular_sesion(app, usuario_con_roles("ASESOR"))
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def ficha(monkeypatch: pytest.MonkeyPatch) -> None:
    vacio = {
        "tasas_interes": [],
        "comisiones": [],
        "seguros": [],
        "sistemas_amortizacion": [],
    }
    del_producto = {
        **vacio,
        "tasas_interes": [4],
        "comisiones": [{"id_comision": 1, "exonerado": False}],
    }
    propios = {
        **vacio,
        "comisiones": [
            {"id_comision": 1, "exonerado": True},
            {"id_comision": 2, "exonerado": False},
        ],
    }
    monkeypatch.setattr(
        repo, "obtener_subproducto", lambda _c, i, **_k: SUB if i == 10 else None
    )
    monkeypatch.setattr(repo, "obtener_producto", lambda _c, i, **_k: PRODUCTO)
    monkeypatch.setattr(repo, "listar_subproductos", lambda _c, _i=None: [SUB])
    monkeypatch.setattr(
        vinculos, "leer", lambda _c, d, _i: del_producto if d == "producto" else propios
    )
    monkeypatch.setattr(catalogos_service, "hoy", lambda: date(2026, 11, 15))
    monkeypatch.setattr(
        catalogos_repo,
        "listar_tasas_interes",
        lambda _c, _h, *_a: [
            {
                "id_tasa_interes": 4,
                "tipo_tasa": "TARJETA_COMPRA",
                "tasa_nominal_anual": Decimal("0.25"),
                "monto_minimo": None,
                "monto_maximo": None,
                "plazo_maximo_meses": None,
                "vigente": True,
            },
            {
                "id_tasa_interes": 5,
                "tipo_tasa": "AHORRO",
                "tasa_nominal_anual": Decimal("0.03"),
                "monto_minimo": None,
                "monto_maximo": None,
                "plazo_maximo_meses": None,
                "vigente": True,
            },
        ],
    )
    comision = {"tipo_calculo": "Fijo", "valor": Decimal("0.50"), "nombre_canal": "POS"}
    monkeypatch.setattr(
        catalogos_repo,
        "listar_comisiones",
        lambda _c: [
            {
                **comision,
                "id_comision": 1,
                "codigo_comision": "GAS",
                "descripcion": "Recargo gasolineras",
            },
            {
                **comision,
                "id_comision": 2,
                "codigo_comision": "EXT",
                "descripcion": "Compra exterior",
            },
        ],
    )
    monkeypatch.setattr(catalogos_repo, "listar_seguros", lambda _c: [])
    monkeypatch.setattr(
        repo,
        "listar_cupos",
        lambda _c, _i: [
            {
                "id_canal": 1,
                "codigo_canal": "VENT",
                "nombre_canal": "Ventanilla",
                "habilitado": True,
                "cupo_diario_maximo": Decimal(500),
                "cupo_mensual_maximo": Decimal(5000),
                "monto_max_transaccion": Decimal(300),
                "max_transacciones_dia": 5,
            },
            {
                "id_canal": 2,
                "codigo_canal": "ATM",
                "nombre_canal": "Cajero",
                "habilitado": False,
            },
        ],
    )


def test_ficha_reune_lo_vigente_y_lo_heredado(ficha):
    r = _cliente(productos_router).get(
        "https://testserver/api/v1/productos/subproductos/10/ficha"
    )
    assert r.status_code == 200, r.text
    f = r.json()
    assert f["subproducto"]["edadMinima"] == 18
    assert [(t["idTasaInteres"], t["delProducto"]) for t in f["tasas"]] == [(4, True)]
    # GAS viene del producto pero el subproducto la exonera: no aparece
    assert [c["codigoComision"] for c in f["comisiones"]] == ["EXT"]
    assert [c["codigoCanal"] for c in f["cupos"]] == ["VENT"]
    assert f["restricciones"] is None  # solo cuentas
    assert (
        _cliente(productos_router)
        .get("https://testserver/api/v1/productos/subproductos/99/ficha")
        .status_code
        == 404
    )


@pytest.mark.parametrize(
    ("nacimiento", "edad"),
    [(date(2010, 6, 1), 16), (date(1990, 11, 16), 35), (None, -1)],
)
def test_productos_para_un_cliente_filtran_por_edad(monkeypatch, nacimiento, edad):
    recibido: dict[str, Any] = {}
    monkeypatch.setattr(catalogos_service, "hoy", lambda: date(2026, 11, 15))
    monkeypatch.setattr(
        catalogos_repo, "fecha_nacimiento_cliente", lambda _c, _i: (True, nacimiento)
    )
    monkeypatch.setattr(
        catalogos_repo,
        "listar_productos",
        lambda _c, _t, _tt, e: recibido.setdefault("edad", e) and [],
    )
    r = _cliente(catalogos_router).get(
        "https://testserver/api/v1/catalogos/productos?idCliente=3"
    )
    assert r.status_code == 200 and recibido["edad"] == edad


def test_cliente_inexistente(monkeypatch):
    monkeypatch.setattr(
        catalogos_repo, "fecha_nacimiento_cliente", lambda _c, _i: (False, None)
    )
    r = _cliente(catalogos_router).get(
        "https://testserver/api/v1/catalogos/productos?idCliente=3"
    )
    assert r.status_code == 404 and r.json()["code"] == "CLIENTE_NO_ENCONTRADO"


def test_edad_cumplida():
    assert catalogos_service.edad_en(date(2008, 11, 16), date(2026, 11, 15)) == 17
    assert catalogos_service.edad_en(date(2008, 11, 15), date(2026, 11, 15)) == 18
