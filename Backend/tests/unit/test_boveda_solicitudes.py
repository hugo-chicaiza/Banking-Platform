"""Solicitudes reales por HTTP, con dos sesiones y repositorio transaccional."""

from copy import deepcopy

import pytest

from tests.boveda_contexto import BASE, BovedaContexto


@pytest.fixture
def ctx(monkeypatch):
    return BovedaContexto(monkeypatch)


def crear(ctx, **datos):
    return ctx.client.post(
        f"{BASE}/bovedas/1/solicitudes-movimiento", json=ctx.movimiento(**datos)
    )


def aprobar(ctx, i=1, **kwargs):
    return ctx.client.post(f"{BASE}/solicitudes-movimiento/{i}/aprobacion", **kwargs)


def test_crear_conserva_datos_y_no_mueve_efectivo(ctx):
    antes = deepcopy(ctx.state)
    r = crear(ctx)
    assert r.status_code == 201, r.text
    assert r.json()["estado"] == "PENDIENTE"
    assert r.json()["idUsuarioSolicitante"] == 7
    assert r.json()["idUsuarioResolucion"] is None
    assert r.json()["monto"] == 40
    assert r.json()["idsMovimientos"] == []
    assert ctx.state["inventarios"] == antes["inventarios"]
    assert ctx.state["bovedas"] == antes["bovedas"]
    assert ctx.state["asientos"] == []


def test_solicitante_no_se_aprueba(ctx):
    crear(ctx)
    assert aprobar(ctx).json()["code"] == "APROBADOR_IGUAL_SOLICITANTE"
    assert ctx.state["solicitudes"][1]["estado"] == "PENDIENTE"


def test_aprobador_proviene_de_segunda_sesion_y_reintento_no_duplica(ctx):
    crear(ctx)
    ctx.como("SUPERVISOR", actor=12)
    primera = aprobar(ctx)
    assert primera.status_code == 201, primera.text
    assert primera.json()[0]["autorizadoPor"] == 12
    assert primera.json()[0]["idUsuarioMovimiento"] == 7
    assert aprobar(ctx).json() == primera.json()
    assert len(ctx.state["movimientos"]) == 1
    assert len(ctx.state["asientos"]) == 1
    solicitud = ctx.client.get(f"{BASE}/solicitudes-movimiento/1").json()
    assert solicitud["estado"] == "EJECUTADA"
    assert solicitud["idUsuarioResolucion"] == 12
    assert solicitud["idsMovimientos"] == [1]


def test_cuerpo_no_puede_cambiar_el_movimiento_al_aprobar(ctx):
    crear(ctx)
    ctx.como("SUPERVISOR", actor=9)
    assert aprobar(ctx, json={"autorizadoPor": 15, "monto": 999}).status_code == 400
    assert not ctx.state["movimientos"]


@pytest.mark.parametrize(
    "extra",
    [
        {"autorizadoPor": 9},
        {"idUsuarioSolicitante": 9},
        {"estado": "EJECUTADA"},
        {"monto": 999},
    ],
)
def test_no_se_aceptan_identidades_o_estado_de_cliente(ctx, extra):
    assert crear(ctx, **extra).status_code == 400
    assert not ctx.state["solicitudes"]


def test_ruta_antigua_no_ejecuta(ctx):
    r = ctx.client.post(
        f"{BASE}/bovedas/1/movimientos", json={**ctx.movimiento(), "autorizadoPor": 9}
    )
    assert r.status_code == 410
    assert r.json()["code"] == "SOLICITUD_AUTORIZACION_REQUERIDA"
    assert not ctx.state["movimientos"]
    assert not ctx.state["solicitudes"]


@pytest.mark.parametrize(
    "accion,actor,estado",
    [("rechazo", 9, "RECHAZADA"), ("cancelacion", 7, "CANCELADA")],
)
def test_resolver_sin_movimientos(ctx, accion, actor, estado):
    crear(ctx)
    ctx.como("SUPERVISOR", actor=actor)
    r = ctx.client.post(
        f"{BASE}/solicitudes-movimiento/1/{accion}",
        json={"motivo": "Operación innecesaria"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["estado"] == estado
    assert r.json()["idUsuarioResolucion"] == actor
    assert r.json()["motivoResolucion"] == "Operación innecesaria"
    assert not ctx.state["movimientos"]
    ctx.como("SUPERVISOR", actor=9)
    assert aprobar(ctx).json()["code"] == "SOLICITUD_MOVIMIENTO_RESUELTA"


def test_cancelacion_solo_por_solicitante_y_rechazo_por_otro(ctx):
    crear(ctx)
    assert (
        ctx.client.post(
            f"{BASE}/solicitudes-movimiento/1/rechazo", json={"motivo": "No"}
        ).status_code
        == 409
    )
    ctx.como("SUPERVISOR", actor=9)
    assert (
        ctx.client.post(
            f"{BASE}/solicitudes-movimiento/1/cancelacion", json={"motivo": "No"}
        ).status_code
        == 403
    )


@pytest.mark.parametrize("motivo", ["", "   ", None])
def test_rechazo_exige_motivo(ctx, motivo):
    crear(ctx)
    ctx.como("SUPERVISOR", actor=9)
    assert (
        ctx.client.post(
            f"{BASE}/solicitudes-movimiento/1/rechazo", json={"motivo": motivo}
        ).status_code
        == 400
    )


def test_otra_agencia_no_consulta_ni_resuelve(ctx):
    crear(ctx)
    ctx.como("SUPERVISOR", actor=9, agencia="002")
    assert ctx.client.get(f"{BASE}/solicitudes-movimiento/1").status_code == 403
    assert aprobar(ctx).status_code == 403
    assert ctx.client.get(f"{BASE}/solicitudes-movimiento").json()["items"] == []


def test_roles_globales_lectura_y_permiso_escritura(ctx):
    from dataclasses import replace

    from app.core.security.permisos import permisos_de

    crear(ctx)
    ctx.como("AUDITOR")
    ctx.usuario = replace(ctx.usuario, permisos=permisos_de(("AUDITOR",)))
    assert ctx.client.get(f"{BASE}/solicitudes-movimiento").json()["total"] == 1
    assert aprobar(ctx).status_code == 403


def test_stock_se_valida_al_aprobar_y_fallo_deja_pendiente(ctx):
    crear(ctx, tipo="EnvioExcedente", desglose=[{"idDenominacion": 1, "cantidad": 8}])
    ctx.state["inventarios"][1][1] = 5
    ctx.state["bovedas"][1]["saldo_actual"] = 100
    ctx.como("SUPERVISOR", actor=9)
    assert aprobar(ctx).json()["code"] == "SALDO_INSUFICIENTE"
    assert ctx.state["solicitudes"][1]["estado"] == "PENDIENTE"
    assert not ctx.state["movimientos"]


def test_sin_contabilidad_se_crea_solicitud_pero_no_se_ejecuta(ctx):
    ctx.fallo_asiento = 1
    assert crear(ctx).status_code == 201
    ctx.como("SUPERVISOR", actor=9)
    assert aprobar(ctx).status_code == 409
    assert ctx.state["solicitudes"][1]["estado"] == "PENDIENTE"
    assert ctx.state["bovedas"][1]["saldo_actual"] == 200
    assert not ctx.state["movimientos"]


def test_datos_de_solicitud_alterados_se_rechazan(ctx):
    crear(ctx)
    ctx.state["detalle_solicitudes"][1][0]["cantidad"] = 5
    ctx.como("SUPERVISOR", actor=9)
    assert aprobar(ctx).json()["code"] == "SOLICITUD_MOVIMIENTO_DESACTUALIZADA"


def test_otro_aprobador_no_repite_solicitud_ejecutada(ctx):
    crear(ctx)
    ctx.como("SUPERVISOR", actor=9)
    assert aprobar(ctx).status_code == 201
    ctx.como("SUPERVISOR", actor=10)
    assert aprobar(ctx).status_code == 409
    assert len(ctx.state["movimientos"]) == 1


def test_lista_paginada_estado_y_detalle_inexistente(ctx):
    crear(ctx)
    crear(ctx)
    assert (
        ctx.client.get(
            f"{BASE}/solicitudes-movimiento?estado=PENDIENTE&pageSize=1"
        ).json()["total"]
        == 2
    )
    assert (
        len(ctx.client.get(f"{BASE}/solicitudes-movimiento?pageSize=1").json()["items"])
        == 1
    )
    assert ctx.client.get(f"{BASE}/solicitudes-movimiento/99").status_code == 404
    assert aprobar(ctx, 99).status_code == 404


def test_idempotencia_de_solicitud(ctx):
    ruta = f"{BASE}/bovedas/1/solicitudes-movimiento"
    headers = {"Idempotency-Key": "solicitud-1"}
    a = ctx.client.post(ruta, json=ctx.movimiento(), headers=headers)
    b = ctx.client.post(ruta, json=ctx.movimiento(), headers=headers)
    assert a.json() == b.json()
    r = ctx.client.post(
        ruta,
        json=ctx.movimiento(desglose=[{"idDenominacion": 1, "cantidad": 3}]),
        headers=headers,
    )
    assert r.json()["code"] == "IDEMPOTENCIA_CONFLICTO"
    assert len(ctx.state["solicitudes"]) == 1


def test_reintento_aprobacion_con_boveda_inactiva_no_repite_efectivo(ctx):
    crear(ctx)
    ctx.como("SUPERVISOR", actor=9)
    primera = aprobar(ctx)
    ctx.state["bovedas"][1]["estado"] = "I"
    assert aprobar(ctx).json() == primera.json()
    assert len(ctx.state["movimientos"]) == 1


def test_reintento_creacion_despues_de_inactivar_devuelve_solicitud(ctx):
    ruta = f"{BASE}/bovedas/1/solicitudes-movimiento"
    headers = {"Idempotency-Key": "misma"}
    primera = ctx.client.post(ruta, json=ctx.movimiento(), headers=headers)
    ctx.state["bovedas"][1]["estado"] = "I"
    assert (
        ctx.client.post(ruta, json=ctx.movimiento(), headers=headers).json()
        == primera.json()
    )
    assert len(ctx.state["solicitudes"]) == 1


def test_historial_publica_vinculo_con_solicitud(ctx):
    crear(ctx)
    ctx.como("SUPERVISOR", actor=9)
    assert aprobar(ctx).json()[0]["idSolicitudMovimiento"] == 1
    assert (
        ctx.client.get(f"{BASE}/bovedas/1/movimientos").json()["items"][0][
            "idSolicitudMovimiento"
        ]
        == 1
    )


def test_admin_solicita_y_otro_admin_aprueba_con_trazabilidad(ctx):
    ctx.como("ADMIN", actor=7)
    assert crear(ctx).status_code == 201
    assert aprobar(ctx).json()["code"] == "APROBADOR_IGUAL_SOLICITANTE"
    ctx.como("ADMIN", actor=9)
    respuesta = aprobar(ctx)
    assert respuesta.status_code == 201, respuesta.text
    assert respuesta.json()[0]["autorizadoPor"] == 9
    assert ctx.client.get(f"{BASE}/bovedas/1/movimientos").json()["total"] == 1
    assert ctx.state["solicitudes"][1]["estado"] == "EJECUTADA"


@pytest.mark.parametrize(
    "accion,actor,estado",
    [("rechazo", 9, "RECHAZADA"), ("cancelacion", 7, "CANCELADA")],
)
def test_admin_resuelve_solicitud_sin_mover_efectivo(ctx, accion, actor, estado):
    ctx.como("ADMIN", actor=7)
    assert crear(ctx).status_code == 201
    ctx.como("ADMIN", actor=actor)
    respuesta = ctx.client.post(
        f"{BASE}/solicitudes-movimiento/1/{accion}",
        json={"motivo": "Cancelada entrega"},
    )
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["estado"] == estado
    assert not ctx.state["movimientos"]


def test_admin_conserva_agencia_de_escritura_y_permisos_explicitos(ctx):
    from dataclasses import replace

    ctx.como("ADMIN", actor=7)
    assert len(ctx.client.get(f"{BASE}/bovedas").json()) == 2
    assert crear(ctx).status_code == 201
    ctx.como("ADMIN", actor=9, agencia="002")
    assert ctx.client.get(f"{BASE}/solicitudes-movimiento/1").status_code == 200
    assert aprobar(ctx).json()["code"] == "SIN_ACCESO_AGENCIA"
    assert crear(ctx).json()["code"] == "SIN_ACCESO_AGENCIA"
    ctx.como("ADMIN", actor=9)
    ctx.usuario = replace(ctx.usuario, permisos=())
    assert aprobar(ctx).json()["code"] == "SIN_PERMISO"
    assert not ctx.state["movimientos"]
