"""CAJ-03 · POST /api/v1/caja/jornadas (pruebas sin BD)."""

from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from app.core.security import auth as auth_mod
from app.modules.caja.router import router
from app.modules.caja.schemas import JornadaOpen
from tests.caja_contexto import (
    BASE,
    CAJA,
    ID_CAJERO,
    ID_SUPERVISOR,
    JORNADA,
    Contexto,
    code,
    crear_contexto,
)


@pytest.fixture
def ctx(monkeypatch: pytest.MonkeyPatch) -> Iterator[Contexto]:
    yield crear_contexto(monkeypatch, router)


def preparar_apertura(ctx: Contexto) -> None:
    ctx.fake("obtener_caja_fisica", CAJA)
    ctx.fake("cajero_asignado", True)
    ctx.fake("jornada_abierta_de_usuario", None)
    ctx.fake("jornada_abierta_de_caja", None)
    ctx.fake("insertar_jornada", 55)
    ctx.fake("obtener_jornada", JORNADA)


def test_caj03_abre_jornada(ctx: Contexto) -> None:
    preparar_apertura(ctx)
    r = ctx.cliente.post(
        f"{BASE}/jornadas", json={"idCajaFisica": 3, "dineroInicial": 100.5}
    )
    assert r.status_code == 201, r.text
    cuerpo = r.json()
    assert cuerpo["idJornadaCaja"] == 55
    assert cuerpo["estado"] == "ABIERTA"
    assert cuerpo["dineroInicial"] == 100.5
    assert cuerpo["fechaHoraApertura"].startswith("2026-11-04T08:30:00")
    # Cajero del vínculo interno y monto en Decimal exacto
    assert ctx.llamadas["insertar_jornada"] == [
        (ID_CAJERO, 3, "001", Decimal("100.5"), None)
    ]
    assert ctx.resultado_auditoria() == "Exitoso"
    assert ctx.eventos[-1].id_registro == "55"
    assert ctx.eventos[-1].usuario is None
    assert "user_01PRUEBA" in ctx.eventos[-1].descripcion


@pytest.mark.parametrize(
    ("cambio", "status", "codigo"),
    [
        (("obtener_caja_fisica", None), 422, "CAJA_FISICA_NO_ENCONTRADA"),
        (("cajero_asignado", False), 409, "CAJERO_NO_ASIGNADO_A_AGENCIA"),
        (
            ("jornada_abierta_de_usuario", JORNADA),
            409,
            "CAJERO_YA_TIENE_JORNADA_ABIERTA",
        ),
        (("jornada_abierta_de_caja", JORNADA), 409, "CAJA_EN_USO"),
        (("obtener_caja_fisica", {**CAJA, "Estado": False}), 409, "CAJA_INACTIVA"),
    ],
)
def test_caj03_reglas(
    ctx: Contexto, cambio: tuple[str, Any], status: int, codigo: str
) -> None:
    preparar_apertura(ctx)
    ctx.fake(*cambio)
    r = ctx.cliente.post(
        f"{BASE}/jornadas", json={"idCajaFisica": 3, "dineroInicial": 100}
    )
    assert r.status_code == status
    assert code(r) == codigo
    assert (
        "insertar_jornada" not in ctx.llamadas or not ctx.llamadas["insertar_jornada"]
    )
    assert ctx.resultado_auditoria() == "Fallido"
    assert codigo in ctx.eventos[-1].descripcion


def test_caj03_sin_vinculo_interno_falla_cerrado(ctx: Contexto) -> None:
    preparar_apertura(ctx)
    ctx.id_interno = None
    r = ctx.cliente.post(
        f"{BASE}/jornadas", json={"idCajaFisica": 3, "dineroInicial": 100}
    )
    assert r.status_code == 403
    assert code(r) == "USUARIO_INTERNO_NO_VINCULADO"
    assert not ctx.llamadas["insertar_jornada"]
    assert ctx.resultado_auditoria() == "Fallido"


@pytest.mark.parametrize(
    "cuerpo",
    [
        {"idCajaFisica": 3, "dineroInicial": -1},
        {"idCajaFisica": 3, "dineroInicial": 1.005},
        {"idCajaFisica": 0, "dineroInicial": 1},
        {"idCajaFisica": 3, "dineroInicial": 1, "idUsuario": 99},
        {"idCajaFisica": 3, "dineroInicial": 1, "observacion": "x" * 501},
        {"idCajaFisica": 3},
    ],
)
def test_caj03_validacion_400(ctx: Contexto, cuerpo: dict[str, Any]) -> None:
    r = ctx.cliente.post(f"{BASE}/jornadas", json=cuerpo)
    assert r.status_code == 400
    assert code(r) == "DATOS_INVALIDOS"
    assert r.json()["errors"]


def test_caj03_json_mal_formado_400(ctx: Contexto) -> None:
    r = ctx.cliente.post(
        f"{BASE}/jornadas",
        content=b"{no-json",
        headers={"content-type": "application/json"},
    )
    assert r.status_code == 400


def test_caj03_rol_supervisor_403(ctx: Contexto) -> None:
    ctx.como("SUPERVISOR", id_interno=ID_SUPERVISOR)
    r = ctx.cliente.post(
        f"{BASE}/jornadas", json={"idCajaFisica": 3, "dineroInicial": 1}
    )
    assert r.status_code == 403


def test_caj03_csrf_origen_no_permitido_403(
    ctx: Contexto, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx.sin_sesion()
    monkeypatch.setattr(auth_mod, "get_frontend_url", lambda: "https://fe.example")
    r = ctx.cliente.post(
        f"{BASE}/jornadas",
        json={"idCajaFisica": 3, "dineroInicial": 1},
        headers={"Origin": "https://malicioso.example"},
    )
    assert r.status_code == 403
    assert code(r) == "ORIGEN_NO_PERMITIDO"


def test_caj03_error_interno_revierte_y_no_filtra_detalle(ctx: Contexto) -> None:
    preparar_apertura(ctx)
    ctx.fake("insertar_jornada", RuntimeError("detalle interno"))
    r = ctx.cliente.post(
        f"{BASE}/jornadas", json={"idCajaFisica": 3, "dineroInicial": 1}
    )
    assert r.status_code == 500
    assert code(r) == "ERROR_INTERNO"
    assert "detalle interno" not in r.text
    # La transacción salió con la excepción: SQLAlchemy hace rollback
    tipo_exc = ctx.conn.begin.return_value.__exit__.call_args.args[0]
    assert tipo_exc is RuntimeError


def test_montos_con_mas_de_dos_decimales_se_rechazan() -> None:
    with pytest.raises(ValidationError):
        JornadaOpen.model_validate({"idCajaFisica": 1, "dineroInicial": "1.001"})
    datos = JornadaOpen.model_validate({"idCajaFisica": 1, "dineroInicial": 0.1})
    assert datos.dinero_inicial == Decimal("0.1")
