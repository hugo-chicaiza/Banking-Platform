"""Pruebas unitarias de CRE-01 y CRE-02 (CR-03 · simulación de crédito).

No requieren base de datos: se monkeypatcha el repositorio.
"""

import itertools
import logging
from datetime import date
from decimal import Decimal
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection

from app.core.database.db import cooperativa
from app.main import app
from app.modules.creditos import amortizacion, repository, service
from app.modules.creditos.schemas import SistemaAmortizacion
from tests.sesion import simular_sesion, usuario_con_roles

HOY = date(2026, 11, 5)
URL_CONDICIONES = "/api/v1/creditos/tipos/1/condiciones"
URL_SIMULACION = "/api/v1/creditos/simulaciones"


@pytest.fixture
def client():
    app.dependency_overrides[cooperativa] = lambda: None
    simular_sesion(app)
    yield TestClient(app)
    app.dependency_overrides.clear()


def _tasa(**cambios: Any) -> dict[str, Any]:
    fila = {
        "id_tipo_credito": 1,
        "tasa_nominal_anual": Decimal("0.1600"),
        "plazo_maximo_meses": 48,
        "recargo_mora_sobre_tasa": Decimal("0.0200"),
        "monto_minimo": Decimal("500.00"),
        "monto_maximo": Decimal("20000.00"),
    }
    return {**fila, **cambios}


def _seguro(**cambios: Any) -> dict[str, Any]:
    fila = {
        "id": 1,
        "codigo": "DESGRAV",
        "nombre": "Seguro de desgravamen",
        "tipo_calculo": "Porcentaje",
        "valor": Decimal("0.050000"),
        "obligatorio": True,
    }
    return {**fila, **cambios}


def _impuesto(**cambios: Any) -> dict[str, Any]:
    fila = {
        "id": 1,
        "codigo": "SOLCA",
        "nombre": "Contribución SOLCA",
        "tipo_calculo": "Porcentaje",
        "valor": Decimal("0.500000"),
        "obligatorio": True,
    }
    return {**fila, **cambios}


def _datos(
    *,
    monkeypatch: pytest.MonkeyPatch,
    tasas: list[dict[str, Any]] | None = None,
    seguros: list[dict[str, Any]] | None = None,
    impuestos: list[dict[str, Any]] | None = None,
) -> None:
    """Reemplaza las tres consultas del repositorio por datos fijos."""
    monkeypatch.setattr(
        repository,
        "tasas_vigentes",
        lambda conn, id_tipo, hoy: [_tasa()] if tasas is None else tasas,
    )
    monkeypatch.setattr(
        repository,
        "seguros_activos",
        lambda conn, id_tipo, hoy: [] if seguros is None else seguros,
    )
    monkeypatch.setattr(
        repository,
        "impuestos_activos",
        lambda conn, id_tipo, hoy: [] if impuestos is None else impuestos,
    )


def _cuerpo(**cambios: Any) -> dict[str, Any]:
    cuerpo = {
        "idTipoCredito": 1,
        "monto": 1000.0,
        "plazoMeses": 12,
        "sistemaAmortizacion": "FRANCES",
        "fechaPrimerVencimiento": "2026-12-05",
    }
    return {**cuerpo, **cambios}


# ---------------------------------------------------------------------------
# CRE-01 · GET /creditos/tipos/{idTipoCredito}/condiciones
# ---------------------------------------------------------------------------


def test_cre01_caso_feliz(client, monkeypatch):
    _datos(seguros=[_seguro()], impuestos=[_impuesto()], monkeypatch=monkeypatch)

    r = client.get(URL_CONDICIONES, params={"monto": 1000, "plazoMeses": 12})

    assert r.status_code == 200
    assert r.json() == {
        "idTipoCredito": 1,
        "tasaNominalAnual": 0.16,
        "plazoMaximoMeses": 48,
        "recargoMoraSobreTasa": 0.02,
        "montoMinimo": 500.0,
        "montoMaximo": 20000.0,
        "seguros": [
            {
                "id": 1,
                "codigo": "DESGRAV",
                "nombre": "Seguro de desgravamen",
                "tipoCalculo": "Porcentaje",
                "valor": 0.05,
                "obligatorio": True,
            }
        ],
        "impuestos": [
            {
                "id": 1,
                "codigo": "SOLCA",
                "nombre": "Contribución SOLCA",
                "tipoCalculo": "Porcentaje",
                "valor": 0.5,
                "obligatorio": True,
            }
        ],
    }


def test_cre01_sin_monto_ni_plazo(client, monkeypatch):
    _datos(monkeypatch=monkeypatch)

    r = client.get(URL_CONDICIONES)

    assert r.status_code == 200
    assert r.json()["seguros"] == [] and r.json()["impuestos"] == []


def test_cre01_monto_sin_limites_acepta_cualquier_monto(client, monkeypatch):
    _datos(tasas=[_tasa(monto_minimo=None, monto_maximo=None)], monkeypatch=monkeypatch)

    r = client.get(URL_CONDICIONES, params={"monto": 999999})

    assert r.status_code == 200
    assert r.json()["montoMinimo"] is None and r.json()["montoMaximo"] is None


@pytest.mark.parametrize(
    "params",
    [
        {"monto": 100},  # por debajo del mínimo
        {"monto": 25000},  # por encima del máximo
        {"plazoMeses": 60},  # mayor al plazo máximo
    ],
)
def test_cre01_sin_tasa_para_monto_o_plazo_es_404(client, monkeypatch, params):
    _datos(monkeypatch=monkeypatch)

    r = client.get(URL_CONDICIONES, params=params)

    assert r.status_code == 404
    assert r.json()["code"] == "TASA_NO_VIGENTE"


def test_cre01_tipo_sin_ninguna_tasa_vigente_es_404(client, monkeypatch):
    _datos(tasas=[], monkeypatch=monkeypatch)

    r = client.get(URL_CONDICIONES)

    assert r.status_code == 404 and r.json()["code"] == "TASA_NO_VIGENTE"


def test_cre01_dos_tasas_vigentes_es_500_y_alerta(client, monkeypatch, caplog):
    _datos(tasas=[_tasa(), _tasa()], monkeypatch=monkeypatch)

    with caplog.at_level(logging.ERROR):
        r = client.get(URL_CONDICIONES, params={"monto": 1000})

    assert r.status_code == 500
    assert r.json()["code"] == "TASA_VIGENTE_DUPLICADA"
    assert "ALERTA" in caplog.text and "55103" in caplog.text


def test_cre01_dos_tasas_pero_solo_una_cubre_el_monto(client, monkeypatch):
    _datos(
        tasas=[
            _tasa(monto_minimo=Decimal(100), monto_maximo=Decimal(999)),
            _tasa(monto_minimo=Decimal(1000), monto_maximo=Decimal(5000)),
        ],
        monkeypatch=monkeypatch,
    )

    r = client.get(URL_CONDICIONES, params={"monto": 1500})

    assert r.status_code == 200 and r.json()["montoMinimo"] == 1000.0


def test_cre01_parametro_desconocido_es_400(client, monkeypatch):
    _datos(monkeypatch=monkeypatch)

    r = client.get(URL_CONDICIONES, params={"plazo": 12})

    assert r.status_code == 400 and r.json()["code"] == "PARAMETRO_INVALIDO"


@pytest.mark.parametrize(
    "ruta,params",
    [
        ("/api/v1/creditos/tipos/0/condiciones", {}),
        ("/api/v1/creditos/tipos/abc/condiciones", {}),
        (URL_CONDICIONES, {"monto": -5}),
        (URL_CONDICIONES, {"plazoMeses": 0}),
        (URL_CONDICIONES, {"plazoMeses": "doce"}),
    ],
)
def test_cre01_valores_invalidos_son_400(client, monkeypatch, ruta, params):
    _datos(monkeypatch=monkeypatch)

    r = client.get(ruta, params=params)

    assert r.status_code == 400


def test_cre01_rol_sin_permiso_es_403(monkeypatch):
    app.dependency_overrides[cooperativa] = lambda: None
    simular_sesion(app, usuario_con_roles("CAJERO"))
    _datos(monkeypatch=monkeypatch)
    try:
        r = TestClient(app).get(URL_CONDICIONES)
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 403 and r.json()["code"] == "SIN_PERMISO"


def test_cre01_sin_sesion_es_401(monkeypatch):
    app.dependency_overrides[cooperativa] = lambda: None
    _datos(monkeypatch=monkeypatch)
    try:
        r = TestClient(app).get(URL_CONDICIONES)
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 401


# ---------------------------------------------------------------------------
# CRE-02 · POST /creditos/simulaciones
# ---------------------------------------------------------------------------


def test_cre02_frances_caso_feliz(client, monkeypatch):
    _datos(monkeypatch=monkeypatch)

    r = client.post(URL_SIMULACION, json=_cuerpo())

    assert r.status_code == 200
    cuerpo = r.json()
    plan = cuerpo["plan"]
    assert len(plan) == 12
    assert cuerpo["tasaNominalAnual"] == 0.16
    # 1000 al 16 % a 12 meses: cuota ≈ 90.73 (capital + interés)
    assert plan[0]["capital"] + plan[0]["interes"] == pytest.approx(90.73, abs=0.01)
    assert plan[0]["interes"] == 13.33
    assert plan[0]["vencimiento"] == "2026-12-05"
    assert plan[-1]["vencimiento"] == "2027-11-05"
    assert plan[0]["saldoInicial"] == 1000.0
    assert plan[-1]["saldoFinal"] == 0.0
    assert cuerpo["cuotaReferencial"] == plan[0]["valor"]
    assert cuerpo["totalSeguros"] == 0.0 and cuerpo["totalImpuestos"] == 0.0


def test_cre02_frances_cuota_fija_y_saldo_cierra_en_cero(client, monkeypatch):
    _datos(monkeypatch=monkeypatch)

    plan = client.post(URL_SIMULACION, json=_cuerpo()).json()["plan"]

    cuotas = [c["capital"] + c["interes"] for c in plan]
    assert all(c == pytest.approx(cuotas[0], abs=0.01) for c in cuotas[:-1])
    assert cuotas[-1] == pytest.approx(
        cuotas[0], abs=0.10
    )  # la última absorbe redondeo
    assert sum(c["capital"] for c in plan) == pytest.approx(1000.0, abs=0.001)
    for anterior, actual in itertools.pairwise(plan):
        assert actual["saldoInicial"] == anterior["saldoFinal"]


def test_cre02_aleman_capital_fijo(client, monkeypatch):
    _datos(monkeypatch=monkeypatch)

    r = client.post(URL_SIMULACION, json=_cuerpo(sistemaAmortizacion="ALEMAN"))

    plan = r.json()["plan"]
    assert r.status_code == 200
    assert plan[0]["capital"] == 83.33 and plan[0]["interes"] == 13.33
    assert plan[1]["capital"] == 83.33
    # El interés baja cada mes porque el saldo baja
    assert plan[1]["interes"] < plan[0]["interes"]
    assert plan[-1]["saldoFinal"] == 0.0
    assert sum(c["capital"] for c in plan) == pytest.approx(1000.0, abs=0.001)


def test_cre02_redondeo_de_la_ultima_cuota():
    plan = amortizacion.calcular_plan(
        monto=Decimal(100),
        plazo_meses=3,
        tasa_nominal_anual=Decimal(0),
        sistema=SistemaAmortizacion.ALEMAN,
        primer_vencimiento=date(2026, 12, 5),
        seguros=[],
        impuestos=[],
    )

    assert [c.capital for c in plan] == [
        Decimal("33.33"),
        Decimal("33.33"),
        Decimal("33.34"),
    ]
    assert plan[-1].saldo_final == 0


def test_cre02_plazo_de_un_mes_frances():
    plan = amortizacion.calcular_plan(
        monto=Decimal(100),
        plazo_meses=1,
        tasa_nominal_anual=Decimal("0.12"),
        sistema=SistemaAmortizacion.FRANCES,
        primer_vencimiento=date(2026, 12, 5),
        seguros=[],
        impuestos=[],
    )

    assert len(plan) == 1
    assert plan[0].capital == Decimal(100)
    assert plan[0].interes == Decimal("1.00")
    assert plan[0].valor == Decimal("101.00")


def test_cre02_tasa_cero_frances_reparte_el_capital():
    plan = amortizacion.calcular_plan(
        monto=Decimal(1200),
        plazo_meses=12,
        tasa_nominal_anual=Decimal(0),
        sistema=SistemaAmortizacion.FRANCES,
        primer_vencimiento=date(2026, 12, 5),
        seguros=[],
        impuestos=[],
    )

    assert all(c.interes == 0 for c in plan)
    assert all(c.capital == Decimal("100.00") for c in plan)


def test_cre02_seguros_e_impuestos_suman_a_cada_cuota(client, monkeypatch):
    _datos(seguros=[_seguro()], impuestos=[_impuesto()], monkeypatch=monkeypatch)

    r = client.post(URL_SIMULACION, json=_cuerpo())

    cuerpo = r.json()
    plan = cuerpo["plan"]
    # Seguro: 0,05 % del saldo inicial de la primera cuota = 1000 × 0,0005 = 0,50
    assert plan[0]["totalSeguros"] == 0.5
    # SOLCA: 0,5 % de 1000 = 5,00 repartido en 12 → 0,42 × 11 y 0,38 la última
    assert plan[0]["totalImpuestos"] == 0.42
    assert plan[-1]["totalImpuestos"] == 0.38
    assert cuerpo["totalImpuestos"] == pytest.approx(5.0, abs=0.001)
    for c in plan:
        assert c["valor"] == pytest.approx(
            c["capital"] + c["interes"] + c["totalSeguros"] + c["totalImpuestos"],
            abs=0.001,
        )
    assert cuerpo["costoTotal"] == pytest.approx(
        sum(c["valor"] for c in plan), abs=0.01
    )
    assert cuerpo["totalIntereses"] == pytest.approx(
        sum(c["interes"] for c in plan), abs=0.01
    )


def test_cre02_rubros_de_valor_fijo():
    plan = amortizacion.calcular_plan(
        monto=Decimal(1200),
        plazo_meses=12,
        tasa_nominal_anual=Decimal(0),
        sistema=SistemaAmortizacion.ALEMAN,
        primer_vencimiento=date(2026, 12, 5),
        seguros=[_seguro(tipo_calculo="Fijo", valor=Decimal("2.50"))],
        impuestos=[_impuesto(tipo_calculo="Fijo", valor=Decimal("12.00"))],
    )

    assert all(c.total_seguros == Decimal("2.50") for c in plan)
    assert all(c.total_impuestos == Decimal("1.00") for c in plan)


def test_cre02_sin_fecha_el_primer_vencimiento_es_un_mes_despues(monkeypatch):
    _datos(monkeypatch=monkeypatch)
    from app.modules.creditos.schemas import SimulacionRequest

    datos = SimulacionRequest.model_validate(
        {
            "idTipoCredito": 1,
            "monto": Decimal(1000),
            "plazoMeses": 2,
            "sistemaAmortizacion": "FRANCES",
        }
    )

    resultado = service.simular(cast(Connection, None), datos, hoy=date(2026, 1, 15))

    assert [c.vencimiento for c in resultado.plan] == [
        date(2026, 2, 15),
        date(2026, 3, 15),
    ]


def test_cre02_vencimiento_el_31_se_ajusta_a_fin_de_mes(client, monkeypatch):
    _datos(monkeypatch=monkeypatch)

    r = client.post(URL_SIMULACION, json=_cuerpo(fechaPrimerVencimiento="2026-01-31"))

    fechas = [c["vencimiento"] for c in r.json()["plan"][:3]]
    assert fechas == ["2026-01-31", "2026-02-28", "2026-03-31"]


def test_sumar_meses_cierra_en_fin_de_mes():
    assert amortizacion.sumar_meses(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert amortizacion.sumar_meses(date(2028, 1, 31), 1) == date(2028, 2, 29)
    assert amortizacion.sumar_meses(date(2026, 11, 5), 2) == date(2027, 1, 5)


@pytest.mark.parametrize("monto", [100, 25000])
def test_cre02_monto_fuera_de_rango_es_422(client, monkeypatch, monto):
    _datos(monkeypatch=monkeypatch)

    r = client.post(URL_SIMULACION, json=_cuerpo(monto=monto))

    assert r.status_code == 422 and r.json()["code"] == "MONTO_FUERA_DE_RANGO"


def test_cre02_plazo_mayor_al_maximo_es_422(client, monkeypatch):
    _datos(monkeypatch=monkeypatch)

    r = client.post(URL_SIMULACION, json=_cuerpo(plazoMeses=60))

    assert r.status_code == 422 and r.json()["code"] == "PLAZO_SUPERA_MAXIMO"


def test_cre02_tipo_sin_tasa_vigente_es_404(client, monkeypatch):
    _datos(tasas=[], monkeypatch=monkeypatch)

    r = client.post(URL_SIMULACION, json=_cuerpo())

    assert r.status_code == 404 and r.json()["code"] == "TASA_NO_VIGENTE"


def test_cre02_dos_tasas_para_el_monto_es_500_y_alerta(client, monkeypatch, caplog):
    _datos(tasas=[_tasa(), _tasa()], monkeypatch=monkeypatch)

    with caplog.at_level(logging.ERROR):
        r = client.post(URL_SIMULACION, json=_cuerpo())

    assert r.status_code == 500 and r.json()["code"] == "TASA_VIGENTE_DUPLICADA"
    assert "55103" in caplog.text


@pytest.mark.parametrize(
    "cambios",
    [
        {"monto": 0},
        {"monto": -10},
        {"monto": 100.123},  # más de 2 decimales
        {"plazoMeses": 0},
        {"idTipoCredito": 0},
        {"sistemaAmortizacion": "AMERICANO"},
        {"fechaPrimerVencimiento": "05/12/2026"},
        {"campoExtra": 1},
    ],
)
def test_cre02_cuerpo_invalido_es_400(client, monkeypatch, cambios):
    _datos(monkeypatch=monkeypatch)

    r = client.post(URL_SIMULACION, json=_cuerpo(**cambios))

    assert r.status_code == 400


def test_cre02_no_escribe_en_la_base(client, monkeypatch):
    """La simulación solo lee: nadie debe llamar a commit."""
    _datos(monkeypatch=monkeypatch)

    class _Conn:
        def commit(self):
            raise AssertionError("CRE-02 no debe hacer commit")

    app.dependency_overrides[cooperativa] = lambda: _Conn()

    assert client.post(URL_SIMULACION, json=_cuerpo()).status_code == 200


def test_cre02_rol_sin_permiso_es_403(monkeypatch):
    app.dependency_overrides[cooperativa] = lambda: None
    simular_sesion(app, usuario_con_roles("CAJERO"))
    _datos(monkeypatch=monkeypatch)
    try:
        r = TestClient(app).post(URL_SIMULACION, json=_cuerpo())
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 403 and r.json()["code"] == "SIN_PERMISO"
