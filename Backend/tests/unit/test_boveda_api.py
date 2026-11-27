"""BOV-01..06: contrato HTTP, permisos y consistencia financiera con rollback."""

from copy import deepcopy
from decimal import Decimal
from typing import Any

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
    ctx.como("ADMIN", agencia=None)
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
    r = ctx.ejecutar(f"{BASE}/bovedas/1/movimientos", json=ctx.movimiento())
    assert r.status_code == 200, r.text
    assert r.json()["estado"] == "RECIBIDO"
    listado = ctx.client.get(
        f"{BASE}/bovedas/1/movimientos?tipoMovimiento=ProvisionExterna&pageSize=1"
    )
    assert listado.json()["total"] == 1
    movimiento = listado.json()["items"][0]
    assert movimiento["saldoPosterior"] == 240
    assert movimiento["fechaMovimiento"].endswith("-05:00")
    assert movimiento["idAsientoContable"] == 1
    assert movimiento["idSolicitudMovimiento"] == r.json()["idSolicitudMovimiento"]
    assert movimiento["desglose"] == [{"idDenominacion": 1, "cantidad": 2}]


@pytest.mark.parametrize(
    "tipo,esperado,asientos",
    [
        ("EnvioExcedente", 160, 2),
        ("ProvisionExterna", 240, 1),
    ],
)
def test_tipos_movimiento_y_naturaleza(ctx, tipo, esperado, asientos):
    r = ctx.ejecutar(f"{BASE}/bovedas/1/movimientos", json=ctx.movimiento(tipo))
    assert r.status_code == 200
    assert ctx.state["bovedas"][1]["saldo_actual"] == esperado
    assert len(ctx.state["asientos"]) == asientos


def test_traslado_liga_ambos_movimientos_y_conserva_efectivo(ctx):
    r = ctx.ejecutar(
        f"{BASE}/bovedas/1/movimientos",
        json=ctx.movimiento("Traslado", idBovedaContraparte=2),
    )
    assert r.status_code == 200, r.text
    a, b = [ctx.state["movimientos"][i] for i in r.json()["idsMovimientos"]]
    assert [a["naturaleza"], b["naturaleza"]] == ["E", "I"]
    assert a["id_movimiento_relacionado"] == b["id_movimiento"]
    assert b["id_movimiento_relacionado"] == a["id_movimiento"]
    assert ctx.state["desgloses"][1] == ctx.state["desgloses"][2]
    assert sum(v["saldo_actual"] for v in ctx.state["bovedas"].values()) == 400
    assert ctx.bloqueos == [1, 2] * 4
    assert len(ctx.state["asientos"]) == 2


@pytest.mark.parametrize(
    "datos,code",
    [
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
    r = ctx.ejecutar(f"{BASE}/bovedas/1/movimientos", json=ctx.movimiento(**datos))
    assert r.status_code in (409, 422), r.text
    assert r.json()["code"] == code
    assert {
        k: v
        for k, v in ctx.state.items()
        if k not in {"solicitudes", "detalle_solicitudes", "cupos_solicitudes"}
    } == {
        k: v
        for k, v in antes.items()
        if k not in {"solicitudes", "detalle_solicitudes", "cupos_solicitudes"}
    }


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
    r = ctx.ejecutar(f"{BASE}/bovedas/1/movimientos", json=ctx.movimiento())
    assert r.json()["code"] == code
    assert not ctx.state["movimientos"]


def test_fallo_segundo_asiento_conserva_despacho_y_revierte_recepcion(ctx):
    ctx.fallo_asiento = 2
    r = ctx.ejecutar(
        f"{BASE}/bovedas/1/movimientos",
        json=ctx.movimiento("Traslado", idBovedaContraparte=2),
    )
    assert r.status_code == 409
    assert ctx.state["solicitudes"][1]["estado"] == "DESPACHADO"
    assert len(ctx.state["movimientos"]) == 1
    assert len(ctx.state["asientos"]) == 1
    assert ctx.state["bovedas"][1]["saldo_actual"] == 160
    assert ctx.state["bovedas"][2]["saldo_actual"] == 200


def test_reintento_traslado_no_duplica_y_clave_reutilizada_conflicto(ctx):
    ruta = f"{BASE}/bovedas/1/movimientos"
    headers = {"Idempotency-Key": "traslado_123"}
    datos = ctx.movimiento("Traslado", idBovedaContraparte=2)
    primera = ctx.ejecutar(ruta, json=datos, headers=headers)
    segunda = ctx.ejecutar(ruta, json=datos, headers=headers)
    assert primera.json() == segunda.json()
    assert len(ctx.state["movimientos"]) == 2
    assert len(ctx.state["asientos"]) == 2
    datos["desglose"][0]["cantidad"] = 3
    assert (
        ctx.ejecutar(ruta, json=datos, headers=headers).json()["code"]
        == "IDEMPOTENCIA_CONFLICTO"
    )


@pytest.mark.parametrize("cantidad", [0, -1, 1.5, True, "2", 2_147_483_648])
def test_movimiento_rechaza_cantidades_invalidas(ctx, cantidad):
    datos = ctx.movimiento(desglose=[{"idDenominacion": 1, "cantidad": cantidad}])
    assert ctx.ejecutar(f"{BASE}/bovedas/1/movimientos", json=datos).status_code == 400


def test_desglose_duplicado_o_campos_extra_se_rechazan(ctx):
    datos = ctx.movimiento()
    datos["desglose"] *= 2
    assert ctx.ejecutar(f"{BASE}/bovedas/1/movimientos", json=datos).status_code == 400
    assert (
        ctx.ejecutar(
            f"{BASE}/bovedas/1/movimientos", json=ctx.movimiento(saldoActual=900)
        ).status_code
        == 400
    )
    assert ctx.client.get(f"{BASE}/bovedas?tipo=General&tipo=Menor").status_code == 400


def test_arqueo_cierra_faltante_guarda_conteo_y_novedad(ctx):
    r = ctx.registrar_conteo(9, idUsuarioResponsable=8)
    assert r.status_code == 201, r.text
    datos = r.json()
    assert datos["estado"] == "FALTANTE"
    assert datos["idUsuarioTestigo"] is None
    assert datos["diferencia"] == -20
    assert datos["diferenciaPorDenominacion"] == [{"idDenominacion": 1, "cantidad": -1}]
    assert ctx.state["detalles"][1][0]["cantidad_esperada"] == 10
    assert ctx.state["bovedas"][1]["saldo_actual"] == 180
    assert datos["novedad"]["idUsuarioResponsable"] == 8
    assert datos["novedad"]["monto"] == 20
    assert datos["novedad"]["estado"] == "PENDIENTE"
    assert len(ctx.state["asientos"]) == 1


def test_arqueo_rechaza_testigo_y_roles_ajenos(ctx):
    assert ctx.registrar_conteo(idUsuarioTestigo=8).status_code == 400
    for rol in ("CAJERO", "ADMIN", "AUDITOR"):
        ctx.como(rol)
        assert ctx.registrar_conteo().status_code == 403
    ctx.como("SUPERVISOR", "ADMIN", agencia="002")
    assert ctx.registrar_conteo().status_code == 403
    assert not ctx.state["arqueos"]


def test_arqueo_admite_conteo_cero_sin_denominaciones(ctx):
    r = ctx.registrar_conteo(desglose=[], idUsuarioResponsable=8)
    assert r.status_code == 201, r.text
    assert r.json()["saldoFisico"] == 0
    assert r.json()["diferenciaPorDenominacion"][0]["cantidad"] == -10


def test_arqueo_exige_cajero_distinto_y_valido_solo_en_faltante(ctx, monkeypatch):
    for responsable in (None, 7):
        assert (
            ctx.registrar_conteo(9, idUsuarioResponsable=responsable).json()["code"]
            == "CAJERO_RESPONSABLE_REQUERIDO"
        )
    assert ctx.registrar_conteo(10, idUsuarioResponsable=8).status_code == 422
    from app.core.api.errors import problema

    def fuera_de_agencia(usuario, agencia, roles):
        assert (usuario, agencia, roles) == (8, "001", {"CAJERO"})
        raise problema(403, "SIN_ACCESO_AGENCIA", "Participante inválido.")

    monkeypatch.setattr(service, "validar_participante_boveda", fuera_de_agencia)
    assert ctx.registrar_conteo(9, idUsuarioResponsable=8).status_code == 403
    assert not ctx.state["arqueos"]


@pytest.mark.parametrize(
    "cantidad,estado,ajustes", [(10, "CUADRADO", 0), (11, "SOBRANTE", 1)]
)
def test_cierre_arqueo_regulariza_inmediato(ctx, cantidad, estado, ajustes):
    r = ctx.registrar_conteo(cantidad)
    assert r.status_code == 201, r.text
    assert r.json()["estado"] == estado
    assert r.json()["novedad"] is None
    assert len(r.json()["idsMovimientosAjuste"]) == ajustes
    assert ctx.state["bovedas"][1]["saldo_actual"] == cantidad * 20
    assert len(ctx.state["asientos"]) == ajustes
    assert (
        ctx.client.post(f"{BASE}/arqueos/1/aprobacion").json()["code"]
        == "ARQUEO_NO_REGISTRADO"
    )


@pytest.mark.parametrize("cantidad_billetes,asientos", [(9, 0), (8, 1)])
def test_arqueo_mixto_registra_denominaciones_y_contabiliza_la_diferencia_neta(
    ctx, cantidad_billetes, asientos
):
    datos: dict[str, Any] = {
        "desglose": [
            {"idDenominacion": 1, "cantidad": cantidad_billetes},
            {"idDenominacion": 2, "cantidad": 2},
        ]
    }
    if asientos:
        datos["idUsuarioResponsable"] = 8
    r = ctx.registrar_conteo(**datos)
    assert r.status_code == 201, r.text
    assert len(r.json()["idsMovimientosAjuste"]) == 2
    assert ctx.state["inventarios"][1] == {1: cantidad_billetes, 2: 2}
    assert ctx.state["bovedas"][1]["saldo_actual"] == (cantidad_billetes + 1) * 20
    assert len(ctx.state["asientos"]) == asientos
    if asientos:
        assert ctx.state["asientos"][0]["monto"] == 20
        assert {
            m["id_asiento_contable"] for m in ctx.state["movimientos"].values()
        } == {1}


def test_fallo_contable_revierte_arqueo_ajustes_y_novedad(ctx):
    ctx.fallo_asiento = 1
    antes = deepcopy(ctx.state)
    assert ctx.registrar_conteo(9, idUsuarioResponsable=8).status_code == 409
    assert ctx.state == antes


def test_aprobacion_legacy_distingue_autor_y_detecta_movimientos_posteriores(ctx):
    ctx.arqueo_historico()
    assert (
        ctx.client.post(f"{BASE}/arqueos/1/aprobacion").json()["code"]
        == "APROBADOR_IGUAL_ARQUEADOR"
    )
    ctx.registrar_conteo(11)
    ctx.como("SUPERVISOR", actor=9)
    assert (
        ctx.client.post(f"{BASE}/arqueos/1/aprobacion").json()["code"]
        == "ARQUEO_DESACTUALIZADO"
    )


def test_aprobacion_rechaza_historico_sin_referencia(ctx):
    ctx.arqueo_historico()
    ctx.state["arqueos"][1]["saldo_teorico"] = None
    ctx.como("SUPERVISOR", actor=9)
    assert (
        ctx.client.post(f"{BASE}/arqueos/1/aprobacion").json()["code"]
        == "ARQUEO_SIN_REFERENCIA"
    )
    assert ctx.client.post(f"{BASE}/arqueos/99/aprobacion").status_code == 404


@pytest.mark.parametrize(
    "metodo,saldo",
    [("JUSTIFICACION", 180), ("DESCUENTO_ROL", 180), ("REPOSICION", 200)],
)
def test_resolucion_novedad_salda_la_cuenta_sin_duplicar_asiento(ctx, metodo, saldo):
    creada = ctx.registrar_conteo(9, idUsuarioResponsable=8)
    assert creada.status_code == 201, creada.text
    ruta = f"{BASE}/arqueos/1/resolucion-novedad"
    datos = {"tipoResolucion": metodo, "observaciones": "Soporte verificado"}
    if metodo == "REPOSICION":
        datos["desglose"] = [{"idDenominacion": 1, "cantidad": 1}]
    else:
        datos["referenciaResolucion"] = "Soporte BOV-001"
    ctx.como("SUPERVISOR", actor=8)
    assert ctx.client.post(ruta, json=datos).status_code == 403
    ctx.como("SUPERVISOR", actor=7)
    resuelta = ctx.client.post(ruta, json=datos)
    assert resuelta.status_code == 200, resuelta.text
    assert resuelta.json()["novedad"]["estado"] == "RESUELTA"
    assert resuelta.json()["novedad"]["idAsientoResolucion"] == 2
    assert ctx.state["bovedas"][1]["saldo_actual"] == saldo
    assert ctx.client.post(ruta, json=datos).json()["code"] == "NOVEDAD_YA_RESUELTA"
    assert len(ctx.state["asientos"]) == 2


def test_novedad_vence_a_las_48_horas_y_rechaza_una_reposicion_parcial(
    ctx, monkeypatch
):
    from datetime import datetime, timedelta

    ahora = datetime(2026, 11, 27, 8)
    monkeypatch.setattr(service.contabilidad, "ahora_ecuador", lambda: ahora)
    creada = ctx.registrar_conteo(9, idUsuarioResponsable=8)
    assert creada.status_code == 201, creada.text
    ahora += timedelta(hours=48)
    listado = ctx.client.get(f"{BASE}/bovedas/1/arqueos").json()
    assert listado["items"][0]["novedad"]["estado"] == "VENCIDA"
    respuesta = ctx.client.post(
        f"{BASE}/arqueos/1/resolucion-novedad",
        json={
            "tipoResolucion": "REPOSICION",
            "observaciones": "Recepción parcial",
            "desglose": [{"idDenominacion": 2, "cantidad": 1}],
        },
    )
    assert respuesta.json()["code"] == "MONTO_REPOSICION_INCORRECTO"
    assert len(ctx.state["asientos"]) == 1
    assert ctx.state["bovedas"][1]["saldo_actual"] == 180


def test_resolver_novedad_revierte_reposicion_con_una_cuenta_distinta(ctx, monkeypatch):
    assert ctx.registrar_conteo(9, idUsuarioResponsable=8).status_code == 201
    antes = deepcopy(ctx.state)

    def asiento_con_otra_cuenta(conn, id_asiento):
        lineas = ctx.movimientos_asiento(conn, id_asiento)
        if id_asiento == 2:
            lineas[1].update(id_cuenta_contable=6, codigo_cuenta="160102")
        return lineas

    monkeypatch.setattr(
        service.repo_contable, "movimientos_asiento", asiento_con_otra_cuenta
    )
    respuesta = ctx.client.post(
        f"{BASE}/arqueos/1/resolucion-novedad",
        json={
            "tipoResolucion": "REPOSICION",
            "observaciones": "Efectivo recibido",
            "desglose": [{"idDenominacion": 1, "cantidad": 1}],
        },
    )
    assert respuesta.json()["code"] == "CUENTA_POR_COBRAR_NO_COMPENSADA"
    assert ctx.state == antes


def test_usuario_sin_vinculo_o_agencia_no_escribe(ctx):
    ctx.como("SUPERVISOR", actor=None)
    assert ctx.registrar_conteo().json()["code"] == "USUARIO_NO_REGISTRADO"
    ctx.como("SUPERVISOR", agencia=None)
    assert ctx.registrar_conteo().json()["code"] == "AGENCIA_NO_ASIGNADA"
    assert not ctx.state["arqueos"]


def test_exceso_limite_bloquea_reserva_de_efectivo(ctx):
    ctx.state["bovedas"][1]["limite_maximo"] = Decimal(210)
    assert (
        ctx.ejecutar(f"{BASE}/bovedas/1/movimientos", json=ctx.movimiento()).status_code
        == 409
    )


def test_escritura_fuera_de_agencia_se_denega_incluso_con_rol_global(ctx):
    ctx.como("SUPERVISOR", "AUDITOR", agencia="002")
    assert (
        ctx.ejecutar(f"{BASE}/bovedas/1/movimientos", json=ctx.movimiento()).status_code
        == 403
    )


def test_movimiento_impide_desbordamiento_de_cantidad(ctx):
    ctx.state["inventarios"][1][1] = 2_147_483_647
    ctx.state["bovedas"][1]["saldo_actual"] = Decimal(20) * 2_147_483_647
    ctx.state["bovedas"][1]["limite_maximo"] = Decimal(20) * 2_147_483_650
    r = ctx.ejecutar(f"{BASE}/bovedas/1/movimientos", json=ctx.movimiento())
    assert r.json()["code"] == "CANTIDAD_FUERA_RANGO"
    assert not ctx.state["movimientos"]


def test_movimiento_impide_desbordamiento_de_monto(ctx):
    ctx.state["catalogo"][1]["valor"] = Decimal("99999999.99")
    ctx.state["bovedas"][1]["saldo_actual"] = Decimal("99999999.99") * 10
    r = ctx.ejecutar(
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
    ctx.arqueo_historico(10)
    ctx.state["arqueos"][1]["saldo_fisico"] += Decimal(20)
    ctx.state["detalles"][1].append(
        {
            "id_denominacion": 2,
            "cantidad": 2,
            "cantidad_esperada": 0,
            "valor": Decimal(10),
        }
    )
    ctx.state["catalogo"][2]["valor"] = Decimal(5)
    ctx.como("SUPERVISOR", actor=9)
    r = ctx.client.post(f"{BASE}/arqueos/1/aprobacion")
    assert r.json()["code"] == "ARQUEO_DESACTUALIZADO"


def test_contador_solo_consulta_agencias_asignadas(ctx):
    from dataclasses import replace

    ctx.como("CONTADOR")
    assert len(ctx.client.get(f"{BASE}/bovedas").json()) == 1
    assert ctx.client.get(f"{BASE}/bovedas?idAgencia=002").status_code == 403
    assert ctx.client.get(f"{BASE}/bovedas/2").status_code == 403
    ctx.usuario = replace(ctx.usuario, id_agencias=("001", "002"))
    assert ctx.client.get(f"{BASE}/bovedas?idAgencia=002").json()[0]["idBoveda"] == 2
    assert ctx.client.get(f"{BASE}/bovedas/2").status_code == 200
