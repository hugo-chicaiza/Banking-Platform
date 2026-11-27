"""Confirmación física y segregación de etapas de los movimientos de bóveda."""

from datetime import date
from decimal import Decimal

import pytest

from app.modules.boveda.solicitudes import service
from tests.boveda_contexto import BASE, BovedaContexto

SOLICITUD = f"{BASE}/solicitudes-movimiento"
GUIA = {"numeroGuia": "GUIA1", "precinto": "P123"}
CONTEO = {"desglose": [{"idDenominacion": 1, "cantidad": 2}]}


@pytest.fixture
def ctx(monkeypatch):
    return BovedaContexto(monkeypatch)


def crear(ctx, **datos):
    return ctx.client.post(
        f"{BASE}/bovedas/1/solicitudes-movimiento", json=ctx.movimiento(**datos)
    )


def etapa(ctx, accion, *, solicitud=1, datos=None):
    return ctx.client.post(f"{SOLICITUD}/{solicitud}/{accion}", json=datos)


def preparar(ctx, tipo="Traslado"):
    ctx.como("CAJERO", actor=7)
    contraparte = {"idBovedaContraparte": 2} if tipo == "Traslado" else {}
    creada = crear(ctx, tipo=tipo, **contraparte)
    assert creada.status_code == 201, creada.text
    assert creada.json()["estado"] == "PENDIENTE"
    ctx.como("SUPERVISOR", actor=9)
    aprobada = etapa(ctx, "aprobacion")
    assert aprobada.status_code == 200, aprobada.text
    assert aprobada.json()["estado"] == "APROBADO"
    assert not ctx.state["movimientos"]
    assert not ctx.state["asientos"]


def test_traslado_descontado_al_despacho_y_acreditado_al_recibir(ctx):
    preparar(ctx)
    despacho = etapa(ctx, "despacho")
    assert despacho.status_code == 400
    despacho = etapa(ctx, "despacho", datos={})
    assert despacho.status_code == 200, despacho.text
    assert despacho.json()["estado"] == "DESPACHADO"
    assert despacho.json()["idUsuarioDespacho"] == 9
    assert [b["saldo_actual"] for b in ctx.state["bovedas"].values()] == [160, 200]
    assert ctx.state["asientos"][0]["naturaleza"] == "E"
    assert etapa(ctx, "despacho", datos={}).status_code == 409
    assert etapa(ctx, "recepcion", datos=CONTEO).status_code == 403
    ctx.como("SUPERVISOR", actor=9, agencia="002")
    assert (
        etapa(ctx, "recepcion", datos=CONTEO).json()["code"] == "DOBLE_CUSTODIA_VIOLADA"
    )
    ctx.como("SUPERVISOR", actor=10, agencia="002")
    assert ctx.client.get(f"{SOLICITUD}/1").status_code == 200
    assert ctx.client.get(SOLICITUD).json()["total"] == 1
    recibido = etapa(ctx, "recepcion", datos=CONTEO)
    assert recibido.status_code == 200, recibido.text
    r = recibido.json()
    assert r["estado"] == "RECIBIDO"
    assert r["idsMovimientos"] == [1, 2]
    assert r["idAsientoConfirmacion"] == 2
    assert r["idAsientoNovedad"] is None
    assert r["conteoConfirmado"] == [
        {"idDenominacion": 1, "cantidad": 2, "valorUnitario": 20}
    ]
    assert [b["saldo_actual"] for b in ctx.state["bovedas"].values()] == [160, 240]
    assert ctx.state["cupos_solicitudes"] == {}
    assert etapa(ctx, "recepcion", datos=CONTEO).status_code == 409


@pytest.mark.parametrize(
    "cantidad,diferencia,tipo",
    [
        (1, -20, "FaltanteTransito"),
        (3, 20, "SobranteTransito"),
        (0, -40, "FaltanteTransito"),
    ],
)
def test_recepcion_con_diferencia_exige_acta_y_liquida_transito(
    ctx, cantidad, diferencia, tipo
):
    preparar(ctx)
    assert etapa(ctx, "despacho", datos=GUIA).status_code == 200
    ctx.como("SUPERVISOR", actor=10, agencia="002")
    datos = {
        "desglose": [{"idDenominacion": 1, "cantidad": cantidad}] if cantidad else []
    }
    assert (
        etapa(ctx, "recepcion", datos=datos).json()["code"] == "ACTA_NOVEDAD_REQUERIDA"
    )
    r = etapa(ctx, "recepcion", datos={**datos, "actaNovedad": "ACTA-123"})
    assert r.status_code == 200, r.text
    assert r.json()["montoConfirmado"] == cantidad * 20
    assert r.json()["diferencia"] == diferencia
    assert r.json()["actaNovedad"] == "ACTA-123"
    assert r.json()["idAsientoNovedad"] is not None
    assert ctx.state["asientos"][-1]["tipo"] == tipo
    assert ctx.state["asientos"][-1]["monto"] == abs(diferencia)
    assert ctx.state["bovedas"][2]["saldo_actual"] == 200 + cantidad * 20


def test_devolucion_reingresa_en_origen_y_conserva_salida(ctx):
    preparar(ctx)
    assert etapa(ctx, "despacho", datos={}).status_code == 200
    ctx.como("SUPERVISOR", actor=10, agencia="002")
    datos = {**CONTEO, "actaNovedad": "DEV-01"}
    assert etapa(ctx, "devolucion", datos=datos).status_code == 403
    ctx.como("SUPERVISOR", actor=9)
    r = etapa(ctx, "devolucion", datos=datos)
    assert r.status_code == 200, r.text
    assert r.json()["estado"] == "DEVUELTO"
    assert ctx.state["movimientos"][2]["tipo_movimiento"] == "RetornoRemesa"
    assert ctx.state["bovedas"][1]["saldo_actual"] == 200
    assert ctx.state["bovedas"][2]["saldo_actual"] == 200
    assert ctx.state["asientos"][-1]["tipo"] == "RetornoRemesa"


def test_provision_requiere_custodia_dual_guia_y_precinto(ctx):
    preparar(ctx, "ProvisionExterna")
    assert (
        etapa(ctx, "recepcion", datos={**GUIA, **CONTEO}).json()["code"]
        == "DOBLE_CUSTODIA_VIOLADA"
    )
    ctx.como("SUPERVISOR", actor=10)
    assert (
        etapa(ctx, "recepcion", datos=CONTEO).json()["code"]
        == "GUIA_PRECINTO_REQUERIDOS"
    )
    r = etapa(ctx, "recepcion", datos={**GUIA, **CONTEO})
    assert r.status_code == 200, r.text
    assert r.json()["estado"] == "RECIBIDO"
    assert r.json()["numeroGuia"] == "GUIA1"
    assert ctx.state["bovedas"][1]["saldo_actual"] == 240


def test_envio_excedente_despacho_y_cierre_liquida_con_comprobante(ctx):
    preparar(ctx, "EnvioExcedente")
    assert etapa(ctx, "despacho", datos={}).json()["code"] == "GUIA_PRECINTO_REQUERIDOS"
    assert etapa(ctx, "despacho", datos=GUIA).status_code == 200
    assert ctx.state["bovedas"][1]["saldo_actual"] == 160
    assert ctx.state["asientos"][0]["tipo"] == "DespachoExcedente"
    assert etapa(ctx, "recepcion", datos=CONTEO).status_code == 409
    r = etapa(ctx, "cierre", datos={"comprobanteBanco": "NOTA-CREDITO-1"})
    assert r.status_code == 200, r.text
    assert r.json()["estado"] == "RECIBIDO"
    assert r.json()["idsMovimientos"] == [1]
    assert r.json()["comprobanteBanco"] == "NOTA-CREDITO-1"
    assert ctx.state["asientos"][-1]["tipo"] == "CierreExcedente"


def test_cupo_se_ocupa_en_ambas_agencias_desde_solicitud(ctx):
    creada = crear(ctx, tipo="Traslado", idBovedaContraparte=2)
    assert creada.status_code == 201
    assert crear(ctx).json()["code"] == "AGENCIA_CON_SOLICITUD_ACTIVA"
    ctx.como("SUPERVISOR", actor=10, agencia="002")
    otro = ctx.client.post(
        f"{BASE}/bovedas/2/solicitudes-movimiento", json=ctx.movimiento()
    )
    assert otro.json()["code"] == "AGENCIA_CON_SOLICITUD_ACTIVA"
    ctx.como("SUPERVISOR", actor=9)
    assert etapa(ctx, "aprobacion").json()["estado"] == "APROBADO"
    r = etapa(ctx, "rechazo", datos={"motivo": "Guía suspendida"})
    assert r.status_code == 200
    assert r.json()["estado"] == "ANULADA"
    assert r.json()["idUsuarioResolucion"] == 9
    assert r.json()["motivoAnulacion"] == "Guía suspendida"
    assert crear(ctx).status_code == 201


def test_reserva_requiere_existencias_y_espacio_en_destino(ctx):
    assert crear(ctx, tipo="Traslado", idBovedaContraparte=2).status_code == 201
    ctx.como("SUPERVISOR", actor=9)
    ctx.state["bovedas"][2]["limite_maximo"] = Decimal(230)
    r = etapa(ctx, "aprobacion")
    assert r.json()["code"] == "LIMITE_BOVEDA_EXCEDIDO"
    assert ctx.state["solicitudes"][1]["estado"] == "PENDIENTE"
    assert ctx.state["cupos_solicitudes"] == {"001": 1, "002": 1}


def test_aprobacion_requiere_cuenta_transito_comun(ctx, monkeypatch):
    assert crear(ctx, tipo="Traslado", idBovedaContraparte=2).status_code == 201
    ctx.como("SUPERVISOR", actor=9)

    def incompatible(conn, agencia, tipo, naturaleza):
        plantilla = ctx.plantilla_movimiento(conn, agencia, tipo, naturaleza)
        return (
            {**plantilla, "credito": 8}
            if (tipo, naturaleza) == ("Traslado", "I")
            else plantilla
        )

    monkeypatch.setattr(service.contable_repo, "plantilla_boveda", incompatible)
    assert etapa(ctx, "aprobacion").json()["code"] == "CUENTA_TRANSITO_INCONSISTENTE"


def test_traslado_conserva_plantillas_versionadas_en_ambas_etapas(ctx, monkeypatch):
    repo = service.contable_repo
    monkeypatch.setattr(
        repo, "obtener_por_id", lambda *args: {"fecha": date(2026, 11, 27)}
    )
    monkeypatch.setattr(
        repo,
        "obtener_plantilla",
        lambda conn, codigo, fecha: {
            "IdPlantillaAsiento": 1 if codigo.endswith("_E") else 2,
        },
    )

    def lineas(conn, plantilla):
        debe, haber = (6, 1) if plantilla == 1 else (1, 6)
        return [
            {
                "IdCuentaContable": cuenta,
                "Estado": True,
                "EsImputable": True,
                "TipoMovimiento": lado,
                "ComponenteImporte": "PRINCIPAL",
            }
            for lado, cuenta in (("DEBITO", debe), ("CREDITO", haber))
        ]

    monkeypatch.setattr(repo, "obtener_lineas_plantilla", lineas)
    preparar(ctx)
    assert ctx.state["solicitudes"][1]["usa_plantilla_versionada"] is True
    assert etapa(ctx, "despacho", datos={}).status_code == 200
    ctx.como("SUPERVISOR", actor=10, agencia="002")
    assert etapa(ctx, "recepcion", datos=CONTEO).status_code == 200
    assert all(asiento["usar_version"] for asiento in ctx.state["asientos"])


def test_fallo_asiento_recepcion_revierte_solo_etapa_actual(ctx):
    preparar(ctx)
    assert etapa(ctx, "despacho", datos={}).status_code == 200
    ctx.como("SUPERVISOR", actor=10, agencia="002")
    ctx.fallo_asiento = 3
    r = etapa(
        ctx,
        "recepcion",
        datos={
            "desglose": [{"idDenominacion": 1, "cantidad": 1}],
            "actaNovedad": "INC-3",
        },
    )
    assert r.status_code == 409, r.text
    assert ctx.state["bovedas"][1]["saldo_actual"] == 160
    assert ctx.state["bovedas"][2]["saldo_actual"] == 200
    assert ctx.state["solicitudes"][1]["estado"] == "DESPACHADO"
    assert len(ctx.state["asientos"]) == 1


def test_solicitante_no_se_aprueba(ctx):
    assert crear(ctx).status_code == 201
    assert etapa(ctx, "aprobacion").json()["code"] == "APROBADOR_IGUAL_SOLICITANTE"
    ctx.como("CAJERO", actor=8)
    assert etapa(ctx, "aprobacion").status_code == 403
    ctx.como("SUPERVISOR", actor=9)
    primera = etapa(ctx, "aprobacion")
    assert primera.status_code == 200
    assert etapa(ctx, "aprobacion").json() == primera.json()
    ctx.como("SUPERVISOR", actor=10)
    assert etapa(ctx, "aprobacion").status_code == 409


@pytest.mark.parametrize(
    "extra",
    [
        {"autorizadoPor": 900},
        {"estado": "RECIBIDO"},
        {"monto": 999},
        {"idUsuarioSolicitante": 900},
    ],
)
def test_no_se_aceptan_identidades_o_estado_de_cliente(ctx, extra):
    assert crear(ctx, **extra).status_code == 400
    assert not ctx.state["solicitudes"]


def test_cuerpo_no_puede_cambiar_movimiento_al_aprobar(ctx):
    assert crear(ctx).status_code == 201
    ctx.como("SUPERVISOR", actor=9)
    assert etapa(ctx, "aprobacion", datos={"monto": 99}).status_code == 400
    assert not ctx.state["movimientos"]


def test_cancelacion_solo_solicitante_y_rechazo_por_otro(ctx):
    assert crear(ctx).status_code == 201
    assert etapa(ctx, "rechazo", datos={"motivo": "No"}).status_code == 409
    ctx.como("CAJERO", actor=8)
    assert etapa(ctx, "cancelacion", datos={"motivo": "No"}).status_code == 403
    ctx.como("CAJERO", actor=7)
    r = etapa(ctx, "cancelacion", datos={"motivo": "No"})
    assert r.json()["estado"] == "CANCELADA"
    assert not ctx.state["cupos_solicitudes"]


def test_destinos_limita_campos_y_requiere_origen_local(ctx):
    ctx.como("CAJERO")
    r = ctx.client.get(f"{BASE}/bovedas/1/destinos")
    assert r.status_code == 200
    assert r.json() == [{"idBoveda": 2, "idAgencia": "002", "codigoBoveda": "B2"}]
    assert ctx.client.get(f"{BASE}/bovedas/2/destinos").status_code == 403


def test_otra_agencia_no_consulta_ni_resuelve(ctx):
    assert crear(ctx).status_code == 201
    ctx.como("SUPERVISOR", actor=9, agencia="002")
    assert ctx.client.get(f"{SOLICITUD}/1").status_code == 403
    assert etapa(ctx, "aprobacion").status_code == 403
    assert ctx.client.get(SOLICITUD).json()["total"] == 0


def test_datos_de_solicitud_alterados_se_rechazan(ctx):
    assert crear(ctx).status_code == 201
    ctx.state["detalle_solicitudes"][1][0]["cantidad"] = 5
    ctx.como("SUPERVISOR", actor=9)
    assert (
        etapa(ctx, "aprobacion").json()["code"] == "SOLICITUD_MOVIMIENTO_DESACTUALIZADA"
    )
