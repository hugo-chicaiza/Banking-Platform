"""Administración de catálogos (/api/v1/catalogos/administracion), sin BD."""

from datetime import date
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.database.db import cooperativa
from app.core.security import audit
from app.modules.catalogos import administracion
from app.modules.catalogos.router import router
from tests.sesion import simular_sesion, usuario_con_roles

BASE = "https://testserver/api/v1/catalogos/administracion"

TASA = {
    "id": "1",
    "estado": "A",
    "tipoTasa": "CREDITO",
    "idTipoCredito": 1,
    "nombreTipoCredito": "Crédito de consumo",
    "tasaNominalAnual": Decimal("0.1600"),
    "recargoMoraSobreTasa": Decimal("0.0200"),
    "montoMinimo": Decimal("500.00"),
    "montoMaximo": Decimal("20000.00"),
    "plazoMaximoMeses": 48,
    "vigenciaDesde": date(2026, 1, 1),
    "vigenciaHasta": None,
}
ANTECEDENTE = {
    "id": "3",
    "estado": "A",
    "nombre": "Lista OFAC",
    "categoria": "Critico",
    "puedeImpedirVinculacion": True,
}


class Conexion:
    """Guarda los UPDATE y aplica los cambios sobre las filas en memoria."""

    def __init__(
        self, filas: dict[str, list[dict[str, Any]]], solapadas: int = 0
    ) -> None:
        self.filas = filas
        self.solapadas = solapadas
        self.updates: list[dict[str, Any]] = []

    def execute(self, sql: Any, params: dict[str, Any]) -> Any:
        texto = str(sql)
        resultado = MagicMock()
        if "COUNT(*)" in texto:
            resultado.scalar_one.return_value = self.solapadas
            return resultado
        self.updates.append(params)
        for lista in self.filas.values():
            for fila in lista:
                if fila["id"] == params["id"]:
                    fila.update({k: params[k] for k in fila if params.get(f"c_{k}")})
        return resultado

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


@pytest.fixture
def bd(monkeypatch: pytest.MonkeyPatch) -> Conexion:
    conn = Conexion(
        {"tasas-interes": [dict(TASA)], "tipos-antecedente": [dict(ANTECEDENTE)]}
    )
    sql_a_clave = {c.listar: c.clave for c in administracion.CATALOGOS.values()}
    monkeypatch.setattr(
        administracion,
        "_rows",
        lambda _c, sql: [dict(f) for f in conn.filas.get(sql_a_clave[sql], [])],
    )
    monkeypatch.setattr(audit, "registrar", lambda _e: None)
    return conn


def _cliente(conn: Conexion, *roles: str) -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[cooperativa] = lambda: conn
    simular_sesion(app, usuario_con_roles(*roles))
    return TestClient(app, raise_server_exceptions=False)


def test_descriptores_sin_agencias_ni_productos(bd):
    claves = [c["clave"] for c in _cliente(bd, "ASESOR").get(BASE).json()]
    assert "tasas-interes" in claves and "paises" in claves
    assert not {"agencias", "productos", "cuentas-contables"} & set(claves)


def test_asesor_consulta_y_no_edita(bd):
    cliente = _cliente(bd, "ASESOR")
    filas = cliente.get(f"{BASE}/tasas-interes").json()
    assert filas[0]["tasaNominalAnual"] == 0.16
    assert (
        cliente.patch(f"{BASE}/tasas-interes/1", json={"estado": "I"}).status_code
        == 403
    )
    assert bd.updates == []


@pytest.mark.parametrize("rol", ["CAJERO", "CONTADOR", "AUDITOR"])
def test_otros_roles_no_entran(bd, rol):
    assert _cliente(bd, rol).get(BASE).status_code == 403


def test_admin_edita_y_desactiva(bd):
    cliente = _cliente(bd, "ADMIN")
    r = cliente.patch(
        f"{BASE}/tasas-interes/1",
        json={"tasaNominalAnual": 0.155, "montoMaximo": 10000},
    )
    assert r.status_code == 200, r.text
    assert r.json()["tasaNominalAnual"] == 0.155 and r.json()["montoMaximo"] == 10000
    r = cliente.patch(
        f"{BASE}/tipos-antecedente/3", json={"estado": "I", "nombre": " Lista ONU "}
    )
    assert (
        r.status_code == 200
        and r.json()["estado"] == "I"
        and r.json()["nombre"] == "Lista ONU"
    )


@pytest.mark.parametrize(
    ("cuerpo", "status"),
    [
        ({}, 400),
        ({"categoria": "EnRevision"}, 400),  # campo de solo lectura
        ({"tasaNominalAnual": 0}, 422),
        ({"tasaNominalAnual": 1.5}, 422),
        ({"tasaNominalAnual": "0.123456"}, 422),
        ({"plazoMaximoMeses": 0}, 422),
        ({"montoMinimo": 30000}, 422),  # mayor que el máximo actual
        ({"vigenciaHasta": "2025-12-31"}, 422),
        ({"estado": "X"}, 422),
    ],
)
def test_validaciones(bd, cuerpo, status):
    clave = "tipos-antecedente" if "categoria" in cuerpo else "tasas-interes"
    id_ = "3" if clave == "tipos-antecedente" else "1"
    r = _cliente(bd, "ADMIN").patch(f"{BASE}/{clave}/{id_}", json=cuerpo)
    assert r.status_code == status, r.text
    assert bd.updates == []


def test_tasa_que_se_solapa_al_reactivar(bd):
    bd.filas["tasas-interes"][0]["estado"] = "I"
    bd.solapadas = 1
    r = _cliente(bd, "ADMIN").patch(f"{BASE}/tasas-interes/1", json={"estado": "A"})
    assert r.status_code == 409 and r.json()["code"] == "TASA_SOLAPADA"


def test_catalogo_o_registro_inexistente(bd):
    cliente = _cliente(bd, "ADMIN")
    assert cliente.get(f"{BASE}/agencias").status_code == 404
    assert (
        cliente.patch(f"{BASE}/tasas-interes/99", json={"estado": "I"}).status_code
        == 404
    )
    assert cliente.patch(
        f"{BASE}/tasas-interes/1;drop", json={"estado": "I"}
    ).status_code in (400, 404, 422)


def test_cada_catalogo_actualiza_solo_sus_campos():
    """Cada campo editable tiene su bandera en el UPDATE fijo del catálogo."""
    for c in administracion.CATALOGOS.values():
        for nombre in (*c.editables, "estado"):
            assert f":c_{nombre} = 1" in c.actualizar, (c.clave, nombre)
            assert f"AS {nombre}" in c.listar, (c.clave, nombre)
