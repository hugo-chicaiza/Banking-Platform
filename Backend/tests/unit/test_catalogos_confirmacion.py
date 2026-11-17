"""Código de confirmación, alta de comisiones y canales, y tasas vinculadas."""

from datetime import date
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.core.database.db import cooperativa
from app.core.security import audit
from app.modules.catalogos import administracion, confirmacion
from app.modules.catalogos.router import router
from app.modules.creditos import repository as creditos_repo
from app.modules.creditos import service as creditos_service
from app.modules.creditos.schemas import SimulacionRequest
from app.modules.productos import vinculos
from tests.sesion import USUARIO, simular_sesion, usuario_con_roles

BASE = "https://testserver/api/v1/catalogos/administracion"


# ---------- Código de confirmación ----------


def test_codigo_de_4_caracteres_valido_solo_para_su_usuario_catalogo_y_tiempo():
    emitido = confirmacion.emitir("u1", "canales", ahora=1000)
    codigo, token = str(emitido["codigo"]), str(emitido["token"])
    assert len(codigo) == 4 and codigo.isalnum() and codigo.upper() == codigo
    assert codigo not in token  # el token no lleva el código en claro
    confirmacion.exigir("u1", "canales", token, codigo.lower(), ahora=1100)
    for usuario, catalogo, cod, ahora in [
        ("u2", "canales", codigo, 1100),  # otro usuario
        ("u1", "denominaciones", codigo, 1100),  # otro catálogo
        ("u1", "canales", "ZZZZ", 1100),  # otro código
        ("u1", "canales", codigo, 1400),  # vencido (5 min)
    ]:
        with pytest.raises(Exception) as exc:
            confirmacion.exigir(usuario, catalogo, token, cod, ahora=ahora)
        assert exc.value.detail["code"] == "CONFIRMACION_INVALIDA"  # type: ignore[attr-defined]
    with pytest.raises(Exception) as exc:
        confirmacion.exigir("u1", "canales", token[:-2] + "00", codigo, ahora=1100)
    assert exc.value.detail["code"] == "CONFIRMACION_INVALIDA"  # type: ignore[attr-defined]
    with pytest.raises(Exception) as exc:
        confirmacion.exigir("u1", "canales", None, None)
    assert exc.value.status_code == 428  # type: ignore[attr-defined]
    confirmacion.exigir("u1", "seguros", None, None)  # catálogo sin confirmación


# ---------- Alta por la API ----------


class Conexion:
    def __init__(self, canal_existe: bool = True) -> None:
        self.canal_existe = canal_existe
        self.inserts: list[dict[str, Any]] = []

    def execute(self, sql: Any, params: dict[str, Any] | None = None) -> Any:
        texto = str(sql)
        r = MagicMock()
        if "SELECT CodigoCanal FROM Canal.Canal" in texto:
            r.scalars.return_value = ["APP", "ATM", "VENT"]
        elif texto.lstrip().startswith("INSERT"):
            self.inserts.append(dict(params or {}))
            sin_canal = "Transacciones.Comisiones" in texto and not self.canal_existe
            r.scalar.return_value = None if sin_canal else "50"
        return r

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


@pytest.fixture
def bd(monkeypatch: pytest.MonkeyPatch) -> Conexion:
    conn = Conexion()
    monkeypatch.setattr(
        administracion, "_rows", lambda _c, _sql: [{"id": "50", "estado": "A"}]
    )
    monkeypatch.setattr(audit, "registrar", lambda _e: None)
    return conn


def _cliente(conn: Conexion, *roles: str) -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[cooperativa] = lambda: conn
    simular_sesion(app, usuario_con_roles(*roles))
    return TestClient(app, raise_server_exceptions=False)


CANAL = {
    "codigo": "kiosco",
    "nombre": "Kiosco",
    "descripcion": "Autoservicio en agencia",
    "modo": "Presencial",
    "requiereTarjeta": True,
    "requierePin": True,
    "requiereTerminal": True,
    "requiereJornadaCaja": False,
}


def test_canal_nuevo_exige_el_codigo_de_confirmacion(bd):
    admin = _cliente(bd, "ADMIN")
    r = admin.post(f"{BASE}/canales", json=CANAL)
    assert r.status_code == 428 and r.json()["code"] == "CONFIRMACION_REQUERIDA"
    emitido = admin.post(f"{BASE}/canales/confirmacion").json()
    assert "lógica de negocio" in emitido["advertencia"]
    cabeceras = {
        "X-Confirmacion-Token": emitido["token"],
        "X-Confirmacion-Codigo": "AAAA",
    }
    assert (
        admin.post(f"{BASE}/canales", json=CANAL, headers=cabeceras).status_code == 422
    )
    cabeceras["X-Confirmacion-Codigo"] = emitido["codigo"]
    r = admin.post(f"{BASE}/canales", json=CANAL, headers=cabeceras)
    assert r.status_code == 201, r.text
    assert bd.inserts[-1]["codigo"] == "KIOSCO"
    sin_tarjeta = {**CANAL, "requiereTarjeta": False}
    assert (
        admin.post(f"{BASE}/canales", json=sin_tarjeta, headers=cabeceras).status_code
        == 422
    )
    assert (
        _cliente(bd, "ASESOR").post(f"{BASE}/canales/confirmacion").status_code == 403
    )
    assert admin.post(f"{BASE}/seguros/confirmacion").status_code == 422


def test_descriptor_marca_confirmacion_y_trae_los_canales(bd):
    d = {c["clave"]: c for c in _cliente(bd, "ASESOR").get(BASE).json()}
    for clave in (
        "sistemas-amortizacion",
        "canales",
        "denominaciones",
        "tipos-movimiento-caja",
    ):
        assert d[clave]["requiereConfirmacion"] and d[clave]["camposAlta"], clave
    assert not d["comisiones"]["requiereConfirmacion"]
    canal = next(
        c for c in d["comisiones"]["camposAlta"] if c["nombre"] == "codigoCanal"
    )
    assert canal["opciones"] == ["APP", "ATM", "VENT"]


COMISION = {
    "codigo": "gas01",
    "tipoComision": "Otro",
    "tipoCalculo": "Fijo",
    "valor": 0.5,
    "montoMinimo": None,
    "montoMaximo": None,
    "codigoCanal": "VENT",
    "descripcion": "Recargo en gasolineras",
    "vigenciaDesde": "2026-12-01",
}


@pytest.mark.parametrize(
    ("cambio", "status", "codigo"),
    [
        ({}, 201, None),
        (
            {"tipoCalculo": "Porcentaje", "valor": 2},
            422,
            "DATOS_INVALIDOS",
        ),  # sin rango
        (
            {
                "tipoCalculo": "Porcentaje",
                "valor": 2,
                "montoMinimo": 1,
                "montoMaximo": 50,
            },
            201,
            None,
        ),
        ({"montoMinimo": 1}, 422, "DATOS_INVALIDOS"),  # rango en una fija
        ({"tipoComision": "Gasolina"}, 422, "DATOS_INVALIDOS"),
    ],
)
def test_alta_de_comisiones(bd, cambio, status, codigo):
    r = _cliente(bd, "ADMIN").post(f"{BASE}/comisiones", json={**COMISION, **cambio})
    assert r.status_code == status, r.text
    if codigo:
        assert r.json()["code"] == codigo


def test_comision_con_canal_inexistente(bd):
    bd.canal_existe = False
    r = _cliente(bd, "ADMIN").post(f"{BASE}/comisiones", json=COMISION)
    assert r.status_code == 422 and r.json()["code"] == "REFERENCIA_INVALIDA"


# ---------- Tasas: varias en el catálogo, una por rango en cada producto ----------


def _tasa(
    id_: int, minimo: int | None, maximo: int | None, desde=date(2026, 1, 1), hasta=None
):
    return {
        "id": id_,
        "tipo": "CREDITO",
        "tipo_credito": 1,
        "minimo": None if minimo is None else Decimal(minimo),
        "maximo": None if maximo is None else Decimal(maximo),
        "desde": desde,
        "hasta": hasta,
    }


def test_tasas_vinculadas_no_pueden_cruzarse():
    assert vinculos._se_solapan(_tasa(1, 500, 20000), _tasa(2, 10000, 40000))
    assert not vinculos._se_solapan(_tasa(1, 500, 20000), _tasa(2, 20001, 40000))
    assert vinculos._se_solapan(_tasa(1, None, None), _tasa(2, 1, 2))
    assert not vinculos._se_solapan(
        _tasa(1, 500, 20000, hasta=date(2026, 6, 30)),
        _tasa(2, 500, 20000, desde=date(2026, 7, 1)),
    )


def test_simulacion_usa_la_tasa_vinculada(monkeypatch):
    pedido: dict[str, Any] = {}

    def tasas(
        _c: Any, tipo: int, _hoy: date, id_producto: Any, id_sub: Any
    ) -> list[dict[str, Any]]:
        pedido.update(tipo=tipo, producto=id_producto, sub=id_sub)
        return []

    monkeypatch.setattr(creditos_repo, "tasas_vigentes", tasas)
    datos = SimulacionRequest.model_validate(
        {
            "idTipoCredito": 1,
            "idProducto": 4,
            "idSubProducto": 9,
            "monto": 1000,
            "plazoMeses": 12,
            "sistemaAmortizacion": "FRANCES",
        }
    )
    with pytest.raises(HTTPException):  # sin tasas vigentes: 404
        creditos_service.simular(MagicMock(), datos, hoy=date(2026, 11, 16))
    assert pedido == {"tipo": 1, "producto": 4, "sub": 9}
    assert USUARIO is not None
