"""TRX-02 · GET /api/v1/transacciones/{idTransaccion} (pruebas sin BD)."""

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


def test_trx02_detalle(ctx: Contexto) -> None:
    ctx.fake("obtener_transaccion", FILA)
    r = ctx.cliente.get(f"{BASE}/2001")
    assert r.status_code == 200
    assert r.json()["idTransaccion"] == 2001
    assert "agenciaOperacion" not in r.json()


@pytest.mark.parametrize("fila", [None, {**FILA, "AgenciaOperacion": "002"}])
def test_trx02_inexistente_o_de_otra_agencia_404(ctx: Contexto, fila: Any) -> None:
    ctx.fake("obtener_transaccion", fila)
    r = ctx.cliente.get(f"{BASE}/2001")
    assert r.status_code == 404
    assert code(r) == "TRANSACCION_NO_ENCONTRADA"


def test_trx02_contador_ve_otra_agencia(ctx: Contexto) -> None:
    ctx.usuario = usuario("CONTADOR")
    ctx.fake("obtener_transaccion", {**FILA, "AgenciaOperacion": "002"})
    assert ctx.cliente.get(f"{BASE}/2001").status_code == 200


@pytest.mark.parametrize("valor", ["0", "abc", "9223372036854775808"])
def test_trx02_id_invalido_400(ctx: Contexto, valor: str) -> None:
    assert ctx.cliente.get(f"{BASE}/{valor}").status_code == 400
