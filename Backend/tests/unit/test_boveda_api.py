"""BOV-01..06: contrato HTTP, permisos y consistencia financiera con rollback."""

from copy import deepcopy
from decimal import Decimal

import pytest

from app.modules.boveda import service
from tests.boveda_contexto import BASE, BovedaContexto


@pytest.fixture
def ctx(monkeypatch):
    return BovedaContexto(monkeypatch)


def test_listado_aisla_agencia_y_detalle_incluye_totales(ctx):
    respuesta = ctx.client.get(f"{BASE}/bovedas")
    assert respuesta.status_code == 200
    assert [b["idBoveda"] for b in respuesta.json()] == [1]
    detalle = ctx.client.get(f"{BASE}/bovedas/1")
    assert detalle.json()["totalDesglose"] == 200
    assert detalle.json()["denominaciones"][0]["subtotal"] == 200
    assert detalle.headers["Cache-Control"] == "no-store"
    assert ctx.client.get(f"{BASE}/bovedas?idAgencia=002").status_code == 403
    assert ctx.client.get(f"{BASE}/bovedas/2").status_code == 403


def test_lectura_global_filtros_y_boveda_inexistente(ctx):
    ctx.como("CONTADOR")
    assert len(ctx.client.get(f"{BASE}/bovedas").json()) == 2
    assert ctx.client.get(f"{BASE}/bovedas?idAgencia=002").json()[0]["idBoveda"] == 2
    assert ctx.client.get(f"{BASE}/bovedas?tipo=Menor").json() == []
    assert ctx.client.get(f"{BASE}/bovedas/99").json()["code"] == "BOVEDA_NO_ENCONTRADA"


@pytest.mark.parametrize(
    "query,code",
    [
        ("sort=monto;DROP,desc", "ORDEN_INVALIDO"),
        ("sort=monto,DESC", "ORDEN_INVALIDO"),
        ("desde=2026-11-15&hasta=2026-11-14", "RANGO_FECHAS_INVALIDO"),
        ("hasta=9999-12-31", "FECHA_HASTA_INVALIDA"),
        ("pageSize=101", "VALIDACION"),
        ("desde=ayer", "VALIDACION"),
    ],
)
def test_filtros_movimientos_invalidos(ctx, query, code):
    r = ctx.client.get(f"{BASE}/bovedas/1/movimientos?{query}")
    assert r.status_code == 400
    if code != "VALIDACION":
        assert r.json()["code"] == code


def test_movimiento_y_consulta_publican_desglose_fecha_y_asiento(ctx):
    r = ctx.client.post(f"{BASE}/bovedas/1/movimientos", json=ctx.movimiento())
    assert r.status_code == 201, r.text
    assert r.json()[0]["saldoPosterior"] == 240
    assert r.json()[0]["fechaMovimiento"].endswith("-05:00")
    assert r.json()[0]["idAsientoContable"] == 1
    listado = ctx.client.get(
        f"{BASE}/bovedas/1/movimientos?tipoMovimiento=ProvisionExterna&pageSize=1"
    )
    assert listado.json()["total"] == 1
    assert listado.json()["items"][0]["desglose"] == [
        {"idDenominacion": 1, "cantidad": 2}
    ]


@pytest.mark.parametrize(
    "tipo,esperado",
    [
        ("EnvioExcedente", 160),
        ("AjusteFaltante", 160),
        ("AjusteSobrante", 240),
        ("ProvisionExterna", 240),
    ],
)
def test_tipos_movimiento_y_naturaleza(ctx, tipo, esperado):
    r = ctx.client.post(f"{BASE}/bovedas/1/movimientos", json=ctx.movimiento(tipo))
    assert r.status_code == 201
    assert ctx.state["bovedas"][1]["saldo_actual"] == esperado
    assert len(ctx.state["asientos"]) == 1


def test_traslado_liga_ambos_movimientos_y_conserva_efectivo(ctx):
    r = ctx.client.post(
        f"{BASE}/bovedas/1/movimientos",
        json=ctx.movimiento("Traslado", idBovedaContraparte=2),
    )
    assert r.status_code == 201, r.text
    a, b = r.json()
    assert [a["naturaleza"], b["naturaleza"]] == ["E", "I"]
    assert a["idMovimientoRelacionado"] == b["idMovimiento"]
    assert b["idMovimientoRelacionado"] == a["idMovimiento"]
    assert a["desglose"] == b["desglose"]
    assert sum(v["saldo_actual"] for v in ctx.state["bovedas"].values()) == 400
    assert ctx.bloqueos == [1, 2]
    assert len(ctx.state["asientos"]) == 2


@pytest.mark.parametrize(
    "datos,code",
    [
        ({"autorizadoPor": 7}, "DOBLE_CUSTODIA_VIOLADA"),
        ({"tipoMovimiento": "Traslado"}, "TRASLADO_REQUIERE_CONTRAPARTE"),
        (
            {"tipoMovimiento": "Traslado", "idBovedaContraparte": 1},
            "CONTRAPARTE_INVALIDA",
        ),
        ({"idBovedaContraparte": 2}, "CONTRAPARTE_INVALIDA"),
        (
            {"tipoMovimiento": "Traslado", "idBovedaContraparte": 99},
            "BOVEDA_NO_ENCONTRADA",
        ),
        (
            {
                "tipoMovimiento": "EnvioExcedente",
                "desglose": [{"idDenominacion": 2, "cantidad": 1}],
            },
            "SALDO_INSUFICIENTE",
        ),
        (
            {"desglose": [{"idDenominacion": 99, "cantidad": 1}]},
            "DENOMINACION_NO_ENCONTRADA",
        ),
    ],
)
def test_rechazos_no_mueven_efectivo(ctx, datos, code):
    antes = deepcopy(ctx.state)
    r = ctx.client.post(f"{BASE}/bovedas/1/movimientos", json=ctx.movimiento(**datos))
    assert r.status_code in (409, 422), r.text
    assert r.json()["code"] == code
    assert ctx.state == antes


@pytest.mark.parametrize(
    "modificacion,code",
    [
        ("inactiva", "BOVEDA_NO_ACTIVA"),
        ("descuadre", "BOVEDA_DESCUADRADA"),
        ("denominacion_inactiva", "DENOMINACION_NO_ACTIVA"),
    ],
)
def test_inconsistencias_impiden_movimiento(ctx, modificacion, code):
    if modificacion == "inactiva":
        ctx.state["bovedas"][1]["estado"] = "I"
    elif modificacion == "descuadre":
        ctx.state["bovedas"][1]["saldo_actual"] = Decimal(999)
    else:
        ctx.state["catalogo"][1]["estado"] = "I"
    r = ctx.client.post(f"{BASE}/bovedas/1/movimientos", json=ctx.movimiento())
    assert r.json()["code"] == code
    assert not ctx.state["movimientos"]


def test_fallo_segundo_asiento_revierte_traslado_completo(ctx):
    antes = deepcopy(ctx.state)
    ctx.fallo_asiento = 2
    r = ctx.client.post(
        f"{BASE}/bovedas/1/movimientos",
        json=ctx.movimiento("Traslado", idBovedaContraparte=2),
    )
    assert r.status_code == 409
    assert ctx.state == antes


def test_reintento_traslado_no_duplica_y_clave_reutilizada_conflicto(ctx):
    ruta = f"{BASE}/bovedas/1/movimientos"
    headers = {"Idempotency-Key": "traslado_123"}
    datos = ctx.movimiento("Traslado", idBovedaContraparte=2)
    primera = ctx.client.post(ruta, json=datos, headers=headers)
    segunda = ctx.client.post(ruta, json=datos, headers=headers)
    assert primera.json() == segunda.json()
    assert len(ctx.state["movimientos"]) == 2
    assert len(ctx.state["asientos"]) == 2
    datos["desglose"][0]["cantidad"] = 3
    assert (
        ctx.client.post(ruta, json=datos, headers=headers).json()["code"]
        == "IDEMPOTENCIA_CONFLICTO"
    )


@pytest.mark.parametrize("cantidad", [0, -1, 1.5, True, "2", 2_147_483_648])
def test_movimiento_rechaza_cantidades_invalidas(ctx, cantidad):
    datos = ctx.movimiento(desglose=[{"idDenominacion": 1, "cantidad": cantidad}])
    assert (
        ctx.client.post(f"{BASE}/bovedas/1/movimientos", json=datos).status_code == 400
    )


def test_desglose_duplicado_o_campos_extra_se_rechazan(ctx):
    datos = ctx.movimiento()
    datos["desglose"] *= 2
    assert (
        ctx.client.post(f"{BASE}/bovedas/1/movimientos", json=datos).status_code == 400
    )
    assert (
        ctx.client.post(
            f"{BASE}/bovedas/1/movimientos", json=ctx.movimiento(saldoActual=900)
        ).status_code
        == 400
    )
    assert ctx.client.get(f"{BASE}/bovedas?tipo=General&tipo=Menor").status_code == 400


def test_arqueo_guarda_referencia_inmutable_y_no_actualiza_saldo(ctx):
    r = ctx.registrar_conteo(9)
    assert r.status_code == 201, r.text
    assert r.json()["diferencia"] == -20
    assert r.json()["diferenciaPorDenominacion"] == [
        {"idDenominacion": 1, "cantidad": -1}
    ]
    assert ctx.state["detalles"][1][0]["cantidad_esperada"] == 10
    assert ctx.state["bovedas"][1]["saldo_actual"] == 200
    assert not ctx.state["movimientos"]


def test_arqueo_omite_denominaciones_como_cero_y_admite_conteo_cero(ctx):
    r = ctx.registrar_conteo(desglose=[{"idDenominacion": 2, "cantidad": 0}])
    assert r.status_code == 201
    assert r.json()["saldoFisico"] == 0
    assert r.json()["diferenciaPorDenominacion"][0]["cantidad"] == -10


def test_arqueo_exige_testigo_distinto_y_valido(ctx, monkeypatch):
    assert (
        ctx.registrar_conteo(idUsuarioTestigo=7).json()["code"]
        == "ARQUEADOR_IGUAL_TESTIGO"
    )
    from app.core.api.errors import problema

    def rechazar(*args):
        raise problema(422, "PARTICIPANTE_NO_HABILITADO", "Participante inválido.")

    monkeypatch.setattr(service, "validar_participante_boveda", rechazar)
    assert ctx.registrar_conteo().status_code == 422
    assert not ctx.state["arqueos"]


@pytest.mark.parametrize(
    "cantidad,esperado,ajustes", [(10, 200, 0), (9, 180, 1), (11, 220, 1)]
)
def test_aprobacion_regulariza_y_no_se_repite(ctx, cantidad, esperado, ajustes):
    assert ctx.registrar_conteo(cantidad).status_code == 201
    ctx.como("SUPERVISOR", actor=9)
    r = ctx.client.post(f"{BASE}/arqueos/1/aprobacion")
    assert r.status_code == 200, r.text
    assert r.json()["estado"] == "APROBADO"
    assert r.json()["idUsuarioAprobador"] == 9
    assert len(r.json()["idsMovimientosAjuste"]) == ajustes
    assert ctx.state["bovedas"][1]["saldo_actual"] == esperado
    assert len(ctx.state["asientos"]) == ajustes
    assert (
        ctx.client.post(f"{BASE}/arqueos/1/aprobacion").json()["code"]
        == "ARQUEO_NO_REGISTRADO"
    )


def test_arqueo_con_faltantes_y_sobrantes_de_igual_monto(ctx):
    assert (
        ctx.registrar_conteo(
            desglose=[
                {"idDenominacion": 1, "cantidad": 9},
                {"idDenominacion": 2, "cantidad": 2},
            ]
        ).status_code
        == 201
    )
    ctx.como("SUPERVISOR", actor=9)
    r = ctx.client.post(f"{BASE}/arqueos/1/aprobacion")
    assert r.status_code == 200, r.text
    assert r.json()["diferencia"] == 0
    assert len(r.json()["idsMovimientosAjuste"]) == 2
    assert ctx.state["inventarios"][1] == {1: 9, 2: 2}
    assert ctx.state["bovedas"][1]["saldo_actual"] == 200


def test_fallo_contable_revierte_ajustes_y_aprobacion(ctx):
    ctx.registrar_conteo(9)
    ctx.como("SUPERVISOR", actor=9)
    ctx.fallo_asiento = 1
    antes = deepcopy(ctx.state)
    assert ctx.client.post(f"{BASE}/arqueos/1/aprobacion").status_code == 409
    assert ctx.state == antes


def test_aprobacion_rechaza_autoria_y_arqueo_desactualizado(ctx):
    ctx.registrar_conteo(9)
    assert (
        ctx.client.post(f"{BASE}/arqueos/1/aprobacion").json()["code"]
        == "APROBADOR_IGUAL_ARQUEADOR"
    )
    ctx.client.post(f"{BASE}/bovedas/1/movimientos", json=ctx.movimiento())
    ctx.como("SUPERVISOR", actor=9)
    assert (
        ctx.client.post(f"{BASE}/arqueos/1/aprobacion").json()["code"]
        == "ARQUEO_DESACTUALIZADO"
    )


def test_aprobacion_rechaza_historico_sin_referencia(ctx):
    ctx.registrar_conteo(9)
    ctx.state["arqueos"][1]["saldo_teorico"] = None
    ctx.como("SUPERVISOR", actor=9)
    assert (
        ctx.client.post(f"{BASE}/arqueos/1/aprobacion").json()["code"]
        == "ARQUEO_SIN_REFERENCIA"
    )
    assert ctx.client.post(f"{BASE}/arqueos/99/aprobacion").status_code == 404


def test_usuario_sin_vinculo_o_agencia_no_escribe(ctx):
    ctx.como("SUPERVISOR", actor=None)
    assert ctx.registrar_conteo().json()["code"] == "USUARIO_NO_REGISTRADO"
    ctx.como("SUPERVISOR", agencia=None)
    assert ctx.registrar_conteo().json()["code"] == "AGENCIA_NO_ASIGNADA"
    assert not ctx.state["arqueos"]


def test_exceso_limites_no_bloquea_efectivo(ctx):
    ctx.state["bovedas"][1]["limite_maximo"] = Decimal(210)
    assert (
        ctx.client.post(
            f"{BASE}/bovedas/1/movimientos", json=ctx.movimiento()
        ).status_code
        == 201
    )


def test_escritura_fuera_de_agencia_se_denega_incluso_con_rol_global(ctx):
    ctx.como("SUPERVISOR", "AUDITOR", agencia="002")
    assert (
        ctx.client.post(
            f"{BASE}/bovedas/1/movimientos", json=ctx.movimiento()
        ).status_code
        == 403
    )


def test_movimiento_impide_desbordamiento_de_cantidad(ctx):
    ctx.state["inventarios"][1][1] = 2_147_483_647
    ctx.state["bovedas"][1]["saldo_actual"] = Decimal(20) * 2_147_483_647
    r = ctx.client.post(f"{BASE}/bovedas/1/movimientos", json=ctx.movimiento())
    assert r.json()["code"] == "CANTIDAD_FUERA_RANGO"
    assert not ctx.state["movimientos"]


def test_movimiento_impide_desbordamiento_de_monto(ctx):
    ctx.state["catalogo"][1]["valor"] = Decimal("99999999.99")
    ctx.state["bovedas"][1]["saldo_actual"] = Decimal("99999999.99") * 10
    r = ctx.client.post(
        f"{BASE}/bovedas/1/movimientos",
        json=ctx.movimiento(
            desglose=[{"idDenominacion": 1, "cantidad": 2_147_483_647}]
        ),
    )
    assert r.json()["code"] == "MONTO_FUERA_RANGO"


def test_arqueo_limita_union_de_conteo_y_existencias(ctx):
    r = ctx.registrar_conteo(
        desglose=[{"idDenominacion": i, "cantidad": 0} for i in range(2, 102)]
    )
    assert r.json()["code"] == "DESGLOSE_EXCEDE_LIMITE"


def test_cambio_valor_de_pieza_sin_existencia_invalida_arqueo(ctx):
    ctx.registrar_conteo(
        desglose=[
            {"idDenominacion": 1, "cantidad": 10},
            {"idDenominacion": 2, "cantidad": 2},
        ]
    )
    ctx.state["catalogo"][2]["valor"] = Decimal(5)
    ctx.como("SUPERVISOR", actor=9)
    r = ctx.client.post(f"{BASE}/arqueos/1/aprobacion")
    assert r.json()["code"] == "ARQUEO_DESACTUALIZADO"
