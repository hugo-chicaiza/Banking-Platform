"""TRX-01 · GET /api/v1/transacciones (pruebas sin BD)."""

from collections.abc import Iterator
from datetime import datetime
from decimal import Decimal
from typing import Any

import pytest

from app.modules.transacciones import repository as repo
from app.modules.transacciones.router import router
from tests.caja_contexto import ID_SUPERVISOR, Contexto, code, crear_contexto, usuario

BASE = "/api/v1/transacciones"


FILA = {
    "IdTransaccion": 2001,
    "NumeroComprobante": "COMP-001",
    "RegistroUnico": "ATM000000002",
    "MTI": "0200",
    "STAN": "000001",
    "RRN": "000000000001",
    "TipoOperacion": "Normal",
    "TipoTransaccion": "Retiro",
    "IdCuenta": 501,
    "IdCuentaDestino": None,
    "IdTarjeta": None,
    "IdCanal": 4,
    "IdTerminal": None,
    "IdAgencia": "001",
    "IdJornadaCaja": None,
    "IdTransaccionRelacionada": None,
    "Monto": Decimal("40.00"),
    "CodigoRespuesta": "00",
    "Estado": "Completada",
    "IdFechaContable": 20261104,
    "FechaHoraSistema": datetime(2026, 11, 4, 10, 15),
    "CreadoPor": 7,
    "NumeroAutorizacion": None,
    "AgenciaOperacion": "001",
}


@pytest.fixture
def ctx(monkeypatch: pytest.MonkeyPatch) -> Iterator[Contexto]:
    yield crear_contexto(
        monkeypatch, router, repo, roles=("SUPERVISOR",), id_interno=ID_SUPERVISOR
    )


def test_trx01_supervisor_solo_su_agencia(ctx: Contexto) -> None:
    ctx.fake("listar_transacciones", ([FILA], 1))
    r = ctx.cliente.get(
        BASE, params={"idCuenta": 501, "estado": "Completada", "sort": "monto,desc"}
    )
    assert r.status_code == 200, r.text
    item = r.json()["items"][0]
    assert item["registroUnico"] == "ATM000000002"
    assert item["mti"] == "0200"
    assert item["monto"] == 40.0
    assert item["fechaHoraSistema"] == "2026-11-04T10:15:00-05:00"
    filtros, orden, offset, limite = ctx.llamadas["listar_transacciones"][0]
    assert filtros["alcance"] == "001"
    assert filtros["id_cuenta"] == 501
    assert orden == ("monto", "desc")
    assert (offset, limite) == (0, 20)


def test_trx01_auditor_sin_limite_de_agencia(ctx: Contexto) -> None:
    ctx.usuario = usuario("AUDITOR", agencia=None)
    ctx.fake("listar_transacciones", ([], 0))
    r = ctx.cliente.get(BASE, params={"idAgencia": "002"})
    assert r.status_code == 200
    filtros = ctx.llamadas["listar_transacciones"][0][0]
    assert filtros["alcance"] is None
    assert filtros["id_agencia"] == "002"


def test_trx01_supervisor_otra_agencia_403(ctx: Contexto) -> None:
    r = ctx.cliente.get(BASE, params={"idAgencia": "002"})
    assert r.status_code == 403
    assert code(r) == "SIN_ACCESO_AGENCIA"


@pytest.mark.parametrize(
    "params",
    [
        {"pageSize": 500},
        {"sort": "Saldo,asc"},
        {"desde": "2026-11-05", "hasta": "2026-11-01"},
        {"tipoTransaccion": "x" * 31},
        {"cuenta": 1},
    ],
)
def test_trx01_parametros_400(ctx: Contexto, params: dict[str, Any]) -> None:
    ctx.fake("listar_transacciones", ([], 0))
    assert ctx.cliente.get(BASE, params=params).status_code == 400


@pytest.mark.parametrize("roles", [("CAJERO",), ("ASESOR",)])
def test_trx01_roles_no_permitidos_403(ctx: Contexto, roles: tuple[str, ...]) -> None:
    ctx.usuario = usuario(*roles)
    assert ctx.cliente.get(BASE).status_code == 403


def test_trx01_sin_sesion_401(ctx: Contexto) -> None:
    ctx.sin_sesion()
    assert ctx.cliente.get(BASE).status_code == 401
