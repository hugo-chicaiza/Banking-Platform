"""CAJ-11 · POST /api/v1/caja/jornadas/{idJornada}/retiros (pruebas sin BD)."""

from collections.abc import Iterator
from decimal import Decimal

import pytest

from app.modules.caja.router import router
from app.modules.transacciones import repository as trx_repo
from tests.caja_contexto import (
    BASE,
    ID_SUPERVISOR,
    TOTALES,
    Contexto,
    code,
    crear_contexto,
)
from tests.caja_ventanilla import (
    DependenciasFalsas,
    preparar_ventanilla,
)


@pytest.fixture
def ctx(monkeypatch: pytest.MonkeyPatch) -> Iterator[Contexto]:
    yield crear_contexto(monkeypatch, router)


CUERPO_RETIRO = {
    "idCuenta": 501,
    "monto": 100.0,
    "registroUnico": "R1B2C3D4E5F6",
    "desglose": [{"idDenominacion": 1, "cantidad": 2}],
}


def preparar_retiro(ctx: Contexto, codigo: str = "00") -> DependenciasFalsas:
    deps = preparar_ventanilla(ctx, "Retiro")
    ctx.fake(
        "autorizar_operacion",
        {"CodigoRespuesta": codigo, "Mensaje": "Aprobada", "Comision": Decimal("0.50")},
        trx_repo,
    )
    ctx.fake("calcular_totales", TOTALES)  # esperado en caja: 150.00
    return deps


def test_caj11_retiro_completo(ctx: Contexto) -> None:
    deps = preparar_retiro(ctx)
    r = ctx.cliente.post(f"{BASE}/jornadas/55/retiros", json=CUERPO_RETIRO)
    assert r.status_code == 201, r.text
    assert r.json()["denominaciones"] == [{"idDenominacion": 1, "cantidad": 2}]
    assert ctx.llamadas["autorizar_operacion"] == [(501, 4, "Retiro", Decimal("100.0"))]
    assert ctx.llamadas["aplicar_movimiento_cuenta"][0][2] == "D"
    assert deps.comisiones == [(5001, Decimal("0.50"))]
    assert ctx.llamadas["id_tipo_movimiento_caja"] == [("RET_E",)]


@pytest.mark.parametrize(
    ("codigo_sp", "status", "codigo"),
    [
        ("51", 422, "FONDOS_INSUFICIENTES"),
        ("05", 409, "CUENTA_NO_ACTIVA"),
        ("61", 422, "OPERACION_RECHAZADA"),
    ],
)
def test_caj11_rechazos_de_autorizacion(
    ctx: Contexto, codigo_sp: str, status: int, codigo: str
) -> None:
    preparar_retiro(ctx, codigo_sp)
    r = ctx.cliente.post(f"{BASE}/jornadas/55/retiros", json=CUERPO_RETIRO)
    assert r.status_code == status
    assert code(r) == codigo
    assert not ctx.llamadas["insertar_transaccion"]


def test_caj11_efectivo_insuficiente_en_caja(ctx: Contexto) -> None:
    preparar_retiro(ctx)
    cuerpo = {k: v for k, v in CUERPO_RETIRO.items() if k != "desglose"}
    r = ctx.cliente.post(f"{BASE}/jornadas/55/retiros", json={**cuerpo, "monto": 200.0})
    assert r.status_code == 409
    assert code(r) == "EFECTIVO_INSUFICIENTE_EN_CAJA"


def test_caj11_solo_cajero(ctx: Contexto) -> None:
    preparar_retiro(ctx)
    ctx.como("SUPERVISOR", id_interno=ID_SUPERVISOR)
    r = ctx.cliente.post(f"{BASE}/jornadas/55/retiros", json=CUERPO_RETIRO)
    assert r.status_code == 403


def _operaciones() -> dict[tuple[str, str], str]:
    """(método, ruta) → operationId según el OpenAPI que genera main.py."""
    from app.main import app

    return {
        (metodo.upper(), ruta): operacion.get("operationId", "")
        for ruta, metodos in app.openapi()["paths"].items()
        for metodo, operacion in metodos.items()
    }


def test_main_tiene_las_18_operaciones_de_caja() -> None:
    ids = {op for (_, ruta), op in _operaciones().items() if "/api/v1/caja" in ruta}
    assert ids == {f"CAJ{n:02d}" for n in range(1, 19)}
