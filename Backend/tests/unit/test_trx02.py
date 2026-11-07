"""TRX-02: pruebas del detalle de transacciones."""

from typing import Any

import pytest

from app.modules.transacciones import repository as repo
from app.modules.transacciones.router import router
from tests.caja_contexto import (
    ID_SUPERVISOR,
    Contexto,
    code,
    crear_contexto,
    usuario,
)

BASE = "/api/v1/transacciones"


@pytest.fixture
def ctx(monkeypatch: pytest.MonkeyPatch) -> Contexto:
    return crear_contexto(
        monkeypatch,
        router,
        repo,
        roles=("SUPERVISOR",),
        id_interno=ID_SUPERVISOR,
    )


@pytest.fixture
def transaccion() -> dict[str, Any]:
    """Datos válidos para verificar la consulta de detalle."""
    return {
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
        "Monto": "40.00",
        "CodigoRespuesta": "00",
        "Estado": "Completada",
        "IdFechaContable": 20261104,
        "FechaHoraSistema": "2026-11-04T10:15:00",
        "CreadoPor": 7,
        "NumeroAutorizacion": None,
        "AgenciaOperacion": "001",
    }


def test_trx02_detalle(
    ctx: Contexto,
    transaccion: dict[str, Any],
) -> None:
    ctx.fake("obtener_transaccion", transaccion)

    respuesta = ctx.cliente.get(f"{BASE}/2001")

    assert respuesta.status_code == 200
    assert respuesta.json()["idTransaccion"] == 2001
    assert "agenciaOperacion" not in respuesta.json()


@pytest.mark.parametrize(
    "otra_agencia",
    [False, True],
)
def test_trx02_inexistente_o_de_otra_agencia_404(
    ctx: Contexto,
    transaccion: dict[str, Any],
    otra_agencia: bool,
) -> None:
    fila = {**transaccion, "AgenciaOperacion": "002"} if otra_agencia else None

    ctx.fake("obtener_transaccion", fila)

    respuesta = ctx.cliente.get(f"{BASE}/2001")

    assert respuesta.status_code == 404
    assert code(respuesta) == "TRANSACCION_NO_ENCONTRADA"


def test_trx02_contador_ve_otra_agencia(
    ctx: Contexto,
    transaccion: dict[str, Any],
) -> None:
    ctx.usuario = usuario("CONTADOR")

    transaccion["AgenciaOperacion"] = "002"
    ctx.fake("obtener_transaccion", transaccion)

    respuesta = ctx.cliente.get(f"{BASE}/2001")

    assert respuesta.status_code == 200


@pytest.mark.parametrize(
    "valor",
    ["0", "abc", "9223372036854775808"],
)
def test_trx02_id_invalido_400(
    ctx: Contexto,
    valor: str,
) -> None:
    respuesta = ctx.cliente.get(f"{BASE}/{valor}")

    assert respuesta.status_code == 400
