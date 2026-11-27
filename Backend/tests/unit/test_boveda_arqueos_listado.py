"""Historial de arqueos: autorización por agencia, filtros y contrato de lectura."""

from copy import deepcopy
from datetime import date, datetime
from unittest.mock import MagicMock

import pytest

from app.modules.boveda import repository
from tests.boveda_contexto import BASE, BovedaContexto

RUTA = f"{BASE}/bovedas/1/arqueos"


@pytest.fixture
def ctx(monkeypatch):
    return BovedaContexto(monkeypatch)


def test_lista_vacia_boveda_inactiva_y_no_encontrada(ctx):
    ctx.state["bovedas"][1]["estado"] = "I"
    respuesta = ctx.client.get(RUTA)
    assert respuesta.status_code == 200
    assert respuesta.json() == {"items": [], "page": 1, "pageSize": 20, "total": 0}
    assert respuesta.headers["Cache-Control"] == "no-store"
    assert respuesta.headers["X-Content-Type-Options"] == "nosniff"
    assert ctx.client.get(f"{BASE}/bovedas/99/arqueos").status_code == 404


def test_historial_paginado_orden_estable_y_sin_escrituras(ctx):
    for i, cantidad in enumerate((10, 10, 11)):
        assert ctx.registrar_conteo(cantidad).status_code == 201
        ctx.state["arqueos"][i + 1]["fecha_hora_arqueo"] = datetime(2026, 11, 17, 10)
    antes = deepcopy(ctx.state)
    pagina = ctx.client.get(RUTA, params={"pageSize": 2}).json()
    assert pagina["total"] == 3
    assert [a["idArqueoBoveda"] for a in pagina["items"]] == [3, 2]
    assert pagina["items"][0]["diferencia"] == 20
    assert pagina["items"][0]["fechaHoraArqueo"].endswith("-05:00")
    segunda = ctx.client.get(RUTA, params={"page": 2, "pageSize": 2}).json()
    assert [a["idArqueoBoveda"] for a in segunda["items"]] == [1]
    ultima = ctx.client.get(RUTA, params={"page": 3, "pageSize": 2}).json()
    assert ultima["items"] == [] and ultima["total"] == 3
    assert ctx.state == antes
    ctx.conn.commit.assert_not_called()


def test_filtros_combinados_y_fechas_inclusivas(ctx):
    for tipo, fecha in (
        ("Programado", datetime(2026, 11, 16, 23, 59)),
        ("Programado", datetime(2026, 11, 17)),
        ("Sorpresivo", datetime(2026, 11, 17, 12)),
        ("Programado", datetime(2026, 11, 17, 23, 59, 59, 999999)),
        ("Programado", datetime(2026, 11, 18)),
    ):
        respuesta = ctx.registrar_conteo(tipoArqueo=tipo)
        ctx.state["arqueos"][respuesta.json()["idArqueoBoveda"]][
            "fecha_hora_arqueo"
        ] = fecha
    ctx.state["arqueos"][2]["estado"] = "ANULADO"
    filtro = {"desde": "2026-11-17", "hasta": "2026-11-17", "tipoArqueo": "Programado"}
    pagina = ctx.client.get(RUTA, params=filtro).json()
    assert [a["idArqueoBoveda"] for a in pagina["items"]] == [4, 2]
    pagina = ctx.client.get(RUTA, params={**filtro, "estado": "CUADRADO"}).json()
    assert [a["idArqueoBoveda"] for a in pagina["items"]] == [4]
    assert ctx.client.get(RUTA, params={"estado": "APROBADO"}).json()["total"] == 0


@pytest.mark.parametrize("rol", ["CONTADOR", "AUDITOR", "ADMIN"])
def test_roles_lectores_consultan_historial_de_agencia_asignada(ctx, rol):
    ctx.registrar_conteo()
    ctx.como(rol, agencia="002")
    from dataclasses import replace

    ctx.usuario = replace(ctx.usuario, id_agencias=("001", "002"))
    assert ctx.client.get(RUTA).json()["total"] == 1


def test_supervisor_no_consulta_historial_de_otra_agencia(ctx):
    ctx.registrar_conteo()
    ctx.como("SUPERVISOR", agencia="002")
    assert ctx.client.get(RUTA).status_code == 403
    ctx.como("SUPERVISOR", agencia=None)
    assert ctx.client.get(RUTA).json()["code"] == "AGENCIA_NO_ASIGNADA"


def test_lista_solo_arqueos_de_la_boveda_indicada(ctx):
    ctx.registrar_conteo()
    ctx.como("SUPERVISOR", agencia="002")
    assert (
        ctx.client.post(f"{BASE}/bovedas/2/arqueos", json=ctx.arqueo()).status_code
        == 201
    )
    segunda = ctx.client.get(f"{BASE}/bovedas/2/arqueos").json()
    assert [a["idArqueoBoveda"] for a in segunda["items"]] == [2]
    ctx.como("SUPERVISOR", agencia="001")
    assert ctx.client.get(RUTA).json()["total"] == 1


def test_historico_sin_referencia_no_inventa_saldos_ni_diferencias(ctx):
    ctx.registrar_conteo()
    ctx.state["arqueos"][1].update(
        saldo_teorico=None, saldo_fisico=None, id_movimiento_corte=None
    )
    respuesta = ctx.client.get(RUTA)
    assert respuesta.status_code == 200, respuesta.text
    item = respuesta.json()["items"][0]
    assert item["saldoTeorico"] is item["saldoFisico"] is item["diferencia"] is None
    assert "idMovimientoCorte" not in item


def test_ajuste_historico_con_vinculo_solo_desde_la_cabecera(ctx):
    ctx.registrar_conteo()
    ctx.state["arqueos"][1]["id_movimiento_ajuste"] = 42
    item = ctx.client.get(RUTA).json()["items"][0]
    assert item["idMovimientoAjuste"] == 42
    assert item["idsMovimientosAjuste"] == [42]


def test_lista_cierre_y_todos_los_ajustes_del_arqueo(ctx):
    cerrado = ctx.registrar_conteo(
        desglose=[
            {"idDenominacion": 1, "cantidad": 9},
            {"idDenominacion": 2, "cantidad": 2},
        ]
    )
    assert cerrado.status_code == 201
    item = ctx.client.get(RUTA, params={"estado": "CUADRADO"}).json()["items"][0]
    assert item["idsMovimientosAjuste"] == cerrado.json()["idsMovimientosAjuste"]
    assert len(item["idsMovimientosAjuste"]) == 2
    assert item["idUsuarioAprobador"] is None
    assert item["fechaHoraAprobacion"] is None
    assert item["diferencia"] == 0


@pytest.mark.parametrize(
    "query",
    [
        "desde=2026-11-18&hasta=2026-11-17",
        "hasta=9999-12-31",
        "desde=0001-01-01",
        "desde=ayer",
        "estado=PENDIENTE",
        "tipoArqueo=Otro",
        "page=0",
        "pageSize=101",
        "page=2147483648",
        "pageSize=1&pageSize=2",
        "otro=valor",
    ],
)
def test_filtros_invalidos_se_rechazan(ctx, query):
    assert ctx.client.get(f"{RUTA}?{query}").status_code == 400


def test_repositorio_parametriza_filtros_y_conserva_total_en_pagina_vacia():
    conn = MagicMock()
    conn.execute.return_value.mappings.return_value = [
        {"id_arqueo_boveda": None, "total": 5}
    ]
    filas, total = repository.listar_arqueos(
        conn, 1, date(2026, 11, 17), date(2026, 11, 17), "ANULADO", "Programado", 4, 2
    )
    assert filas == [] and total == 5
    consulta, params = conn.execute.call_args.args
    assert "IdBoveda = :boveda" in str(consulta)
    assert "Programado" not in str(consulta)
    assert params["hasta"] == date(2026, 11, 18)
    assert params["offset"] == 6 and params["limite"] == 8
    assert params["estado"] == "ANULADO" and params["tipo"] == "Programado"
