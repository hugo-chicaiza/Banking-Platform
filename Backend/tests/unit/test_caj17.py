"""CAJ-17 · POST /api/v1/caja/jornadas/{idJornada}/cuadre/autorizacion (pruebas sin BD)."""

from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import pytest

from app.modules.caja.router import router
from tests.caja_contexto import (
    BASE,
    ID_CAJERO,
    ID_SUPERVISOR,
    JORNADA,
    TOTALES,
    Contexto,
    code,
    crear_contexto,
    cuadre,
)


@pytest.fixture
def ctx(monkeypatch: pytest.MonkeyPatch) -> Iterator[Contexto]:
    yield crear_contexto(monkeypatch, router)


def preparar_autorizacion(ctx: Contexto, **cambios: Any) -> None:
    ctx.como("SUPERVISOR", id_interno=ID_SUPERVISOR)
    ctx.fake("obtener_jornada", JORNADA)
    contado = cuadre(
        SaldoFinalFisico=Decimal("149.99"),
        DiferenciaDinero=Decimal("-0.01"),
        EstadoCuadre="FALTANTE",
    )
    ctx.fake("obtener_cuadre_de_jornada", {**contado, **cambios})
    ctx.fake("autorizar_cuadre", True)
    # Sin movimientos después del conteo: los totales actuales son los del cuadre
    ctx.fake("calcular_totales", TOTALES)
    ctx.fake("obtener_cuadre", {**contado, "IdAutorizadoPor": ID_SUPERVISOR})


def test_caj17_autoriza_con_observacion(ctx: Contexto) -> None:
    preparar_autorizacion(ctx)
    r = ctx.cliente.post(
        f"{BASE}/jornadas/55/cuadre/autorizacion",
        json={"autorizadoPor": ID_SUPERVISOR, "observaciones": "Faltante de 1 ctv"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["idAutorizadoPor"] == ID_SUPERVISOR
    assert ctx.llamadas["autorizar_cuadre"] == [
        (70, ID_SUPERVISOR, "Faltante de 1 ctv")
    ]


@pytest.mark.parametrize(
    ("cuerpo", "cambios", "status", "codigo"),
    [
        (
            {"autorizadoPor": 99, "observaciones": "x"},
            {},
            422,
            "AUTORIZADOR_NO_COINCIDE",
        ),
        (
            {"autorizadoPor": ID_SUPERVISOR, "observaciones": "x"},
            {"IdUsuario": ID_SUPERVISOR},
            409,
            "DOBLE_CUSTODIA_VIOLADA",
        ),
        (
            {"autorizadoPor": ID_SUPERVISOR},
            {"SaldoFinalFisico": None},
            409,
            "CUADRE_PENDIENTE_DE_CONTEO",
        ),
        ({"autorizadoPor": ID_SUPERVISOR}, {}, 422, "OBSERVACION_REQUERIDA"),
        (
            {"autorizadoPor": ID_SUPERVISOR, "observaciones": "x"},
            {"IdAutorizadoPor": 10},
            409,
            "CUADRE_YA_AUTORIZADO",
        ),
    ],
)
def test_caj17_reglas(
    ctx: Contexto,
    cuerpo: dict[str, Any],
    cambios: dict[str, Any],
    status: int,
    codigo: str,
) -> None:
    preparar_autorizacion(ctx, **cambios)
    r = ctx.cliente.post(f"{BASE}/jornadas/55/cuadre/autorizacion", json=cuerpo)
    assert r.status_code == status
    assert code(r) == codigo
    assert not ctx.llamadas["autorizar_cuadre"]


def test_caj17_sin_vinculo_y_cajero(ctx: Contexto) -> None:
    preparar_autorizacion(ctx)
    ctx.id_interno = None
    cuerpo = {"autorizadoPor": ID_SUPERVISOR, "observaciones": "x"}
    r = ctx.cliente.post(f"{BASE}/jornadas/55/cuadre/autorizacion", json=cuerpo)
    assert code(r) == "USUARIO_INTERNO_NO_VINCULADO"
    ctx.como("CAJERO", id_interno=ID_CAJERO)
    r = ctx.cliente.post(f"{BASE}/jornadas/55/cuadre/autorizacion", json=cuerpo)
    assert r.status_code == 403
