"""CAJ-09 · POST /api/v1/caja/jornadas/{idJornada}/depositos (pruebas sin BD)."""

from collections.abc import Iterator
from datetime import datetime
from decimal import Decimal
from typing import Any
from unittest.mock import Mock

import pytest

from app.modules.caja import service
from app.modules.caja.router import router
from app.modules.transacciones import repository as trx_repo
from app.modules.transacciones.dependencias import DatosAsiento
from tests.caja_contexto import (
    BASE,
    CUADRE,
    ID_CAJERO,
    JORNADA,
    TRANSACCION,
    Contexto,
    code,
    crear_contexto,
)
from tests.caja_ventanilla import (
    CUERPO_DEPOSITO,
    preparar_ventanilla,
)


@pytest.fixture
def ctx(monkeypatch: pytest.MonkeyPatch) -> Iterator[Contexto]:
    yield crear_contexto(monkeypatch, router)


def test_caj09_sin_configuracion_responde_501_sin_tocar_bd(ctx: Contexto) -> None:
    ctx.fake("buscar_por_registro_unico", None, trx_repo)
    r = ctx.cliente.post(f"{BASE}/jornadas/55/depositos", json=CUERPO_DEPOSITO)
    assert r.status_code == 501
    assert code(r) == "OPERACION_NO_HABILITADA"
    assert not ctx.llamadas["buscar_por_registro_unico"]
    ctx.conn.begin.assert_not_called()
    assert ctx.resultado_auditoria() == "Fallido"


def test_caj09_deposito_completo(ctx: Contexto) -> None:
    deps = preparar_ventanilla(ctx)
    r = ctx.cliente.post(f"{BASE}/jornadas/55/depositos", json=CUERPO_DEPOSITO)
    assert r.status_code == 201, r.text
    cuerpo = r.json()
    assert cuerpo["numeroComprobante"] == "COMP-000123"
    assert cuerpo["codigoRespuesta"] == "00"
    assert cuerpo["saldoDisponible"] == 1150.0
    assert cuerpo["denominaciones"] is None
    assert "idempotent-replay" not in r.headers
    datos = ctx.llamadas["insertar_transaccion"][0][0]
    assert datos["mti"] == "0200"
    assert datos["creado_por"] == ID_CAJERO
    assert datos["monto"] == Decimal("150.0")
    assert datos["id_jornada"] == 55
    assert ctx.llamadas["aplicar_movimiento_cuenta"] == [
        (5001, 501, "C", None, Decimal("150.0"), 20261104)
    ]
    assert deps.asientos[0].tipo_transaccion == "Deposito"
    assert ctx.llamadas["id_tipo_movimiento_caja"] == [("DEP_I",)]
    assert ctx.llamadas["insertar_movimiento_caja"][0][6] == 777  # id del asiento


@pytest.mark.parametrize("hora", ["18:59:59", "19:00:00"])
def test_deposito_comparte_instante_con_el_calendario(
    ctx: Contexto, monkeypatch: pytest.MonkeyPatch, hora: str
) -> None:
    preparar_ventanilla(ctx)
    instante = datetime.fromisoformat(f"2026-11-06T{hora}")
    reloj = Mock(side_effect=[instante, AssertionError("Se volvió a leer el reloj")])
    monkeypatch.setattr(service, "ahora_ecuador", reloj)

    r = ctx.cliente.post(f"{BASE}/jornadas/55/depositos", json=CUERPO_DEPOSITO)

    assert r.status_code == 201, r.text
    reloj.assert_called_once_with()
    assert ctx.llamadas["id_fecha_contable"] == [(instante,)]
    datos = ctx.llamadas["insertar_transaccion"][0][0]
    assert datos["fecha_hora"] == instante


def test_caj09_reintento_idempotente_200(ctx: Contexto) -> None:
    preparar_ventanilla(ctx)
    ctx.fake("buscar_por_registro_unico", TRANSACCION, trx_repo)
    r = ctx.cliente.post(f"{BASE}/jornadas/55/depositos", json=CUERPO_DEPOSITO)
    assert r.status_code == 200
    assert r.headers["idempotent-replay"] == "true"
    assert r.json()["idTransaccion"] == 5001
    assert not ctx.llamadas["insertar_transaccion"]


@pytest.mark.parametrize(
    "previa",
    [
        {**TRANSACCION, "Monto": Decimal("151.00")},
        {**TRANSACCION, "IdCuenta": 502},
        {**TRANSACCION, "CreadoPor": 8},
        {**TRANSACCION, "TipoTransaccion": "Retiro"},
    ],
)
def test_caj09_registro_unico_reutilizado_409(
    ctx: Contexto, previa: dict[str, Any]
) -> None:
    preparar_ventanilla(ctx)
    ctx.fake("buscar_por_registro_unico", previa, trx_repo)
    r = ctx.cliente.post(f"{BASE}/jornadas/55/depositos", json=CUERPO_DEPOSITO)
    assert r.status_code == 409
    assert code(r) == "REGISTRO_UNICO_REUTILIZADO"


@pytest.mark.parametrize(
    ("cambio", "fake", "status", "codigo"),
    [
        ({"desglose": None}, None, 422, "DESGLOSE_REQUERIDO"),
        (
            {"desglose": [{"idDenominacion": 1, "cantidad": 2}]},
            None,
            422,
            "DESGLOSE_NO_COINCIDE_CON_MONTO",
        ),
        ({}, ("valores_denominaciones", {}), 422, "DENOMINACION_NO_ENCONTRADA"),
        (
            {},
            ("obtener_jornada", {**JORNADA, "Estado": "CERRADA"}),
            409,
            "JORNADA_NO_ABIERTA",
        ),
        ({}, ("dotacion_inicial_registrada", False), 409, "DOTACION_INICIAL_PENDIENTE"),
        ({}, ("obtener_cuadre_de_jornada", CUADRE), 409, "JORNADA_EN_CUADRE"),
    ],
)
def test_caj09_reglas(
    ctx: Contexto, cambio: dict[str, Any], fake: Any, status: int, codigo: str
) -> None:
    preparar_ventanilla(ctx)
    if fake:
        ctx.fake(*fake)
    cuerpo = {k: v for k, v in {**CUERPO_DEPOSITO, **cambio}.items() if v is not None}
    r = ctx.cliente.post(f"{BASE}/jornadas/55/depositos", json=cuerpo)
    assert r.status_code == status
    assert code(r) == codigo
    assert not ctx.llamadas["insertar_transaccion"]


def test_caj09_cuenta_no_activa_o_inexistente(ctx: Contexto) -> None:
    preparar_ventanilla(ctx)
    ctx.fake("obtener_cuenta", {"Estado": "Bloqueada"}, trx_repo)
    r = ctx.cliente.post(f"{BASE}/jornadas/55/depositos", json=CUERPO_DEPOSITO)
    assert (r.status_code, code(r)) == (409, "CUENTA_NO_ACTIVA")
    ctx.fake("obtener_cuenta", None, trx_repo)
    r = ctx.cliente.post(f"{BASE}/jornadas/55/depositos", json=CUERPO_DEPOSITO)
    assert (r.status_code, code(r)) == (422, "CUENTA_NO_ENCONTRADA")


def test_caj09_falla_del_asiento_revierte_todo(ctx: Contexto) -> None:
    deps = preparar_ventanilla(ctx)

    def sin_plantilla(conn: Any, datos: DatosAsiento) -> int:
        raise RuntimeError("sin plantilla contable")

    deps.contabilizar = sin_plantilla  # type: ignore[method-assign]
    r = ctx.cliente.post(f"{BASE}/jornadas/55/depositos", json=CUERPO_DEPOSITO)
    assert r.status_code == 500
    assert ctx.conn.begin.return_value.__exit__.call_args.args[0] is RuntimeError
    assert not ctx.llamadas["insertar_movimiento_caja"]


@pytest.mark.parametrize(
    "cambio",
    [
        {"registroUnico": "CORTO"},
        {"registroUnico": "A1B2C3D4E5F6X"},
        {"registroUnico": "A1B2-3D4E5F6"},
        {"monto": 0},
        {"monto": 1.001},
        {"monto": "1e30"},
        {"observacion": "x" * 301},
    ],
)
def test_caj09_validacion_400(ctx: Contexto, cambio: dict[str, Any]) -> None:
    preparar_ventanilla(ctx)
    r = ctx.cliente.post(
        f"{BASE}/jornadas/55/depositos", json={**CUERPO_DEPOSITO, **cambio}
    )
    assert r.status_code == 400
