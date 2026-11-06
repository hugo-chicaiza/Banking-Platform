"""CAJ-07 · POST /api/v1/caja/jornadas/{idJornada}/dotaciones (pruebas sin BD)."""

from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import DBAPIError

from app.core.api.errors import traducir_error_bd
from app.core.database.procedimientos import ejecutar_con_salidas
from app.modules.caja.router import router
from app.modules.caja.schemas import Desglose
from app.modules.caja.service import desglose_json, validar_custodia
from tests.caja_contexto import (
    BASE,
    DOTACION,
    ID_CAJERO,
    ID_SUPERVISOR,
    JORNADA,
    Contexto,
    code,
    crear_contexto,
    error_bd,
    jornada,
)


@pytest.fixture
def ctx(monkeypatch: pytest.MonkeyPatch) -> Iterator[Contexto]:
    yield crear_contexto(monkeypatch, router)


CUERPO_DOTACION = {
    "idBoveda": 2,
    "autorizadoPor": ID_SUPERVISOR,
    "tipoDotacion": "INICIAL",
    "desglose": [{"idDenominacion": 1, "cantidad": 10}],
}


def preparar_dotacion(ctx: Contexto) -> None:
    ctx.fake("obtener_jornada", JORNADA)
    ctx.fake("id_fecha_contable", 20261104)
    ctx.fake(
        "registrar_dotacion",
        {"IdDotacionCaja": 801, "IdMovimientoBoveda": 9001, "BovedaBajoMinimo": True},
    )
    ctx.fake("obtener_dotacion", DOTACION)


def test_caj07_registra_dotacion_inicial(ctx: Contexto) -> None:
    preparar_dotacion(ctx)
    r = ctx.cliente.post(f"{BASE}/jornadas/55/dotaciones", json=CUERPO_DOTACION)
    assert r.status_code == 201, r.text
    cuerpo = r.json()
    assert cuerpo["idDotacionCaja"] == 801
    assert cuerpo["bovedaBajoMinimo"] is True
    assert cuerpo["monto"] == 100.5
    assert ctx.llamadas["registrar_dotacion"] == [
        (
            55,
            2,
            ID_SUPERVISOR,
            "INICIAL",
            '[{"IdDenominacion": 1, "Cantidad": 10}]',
            None,
            20261104,
        )
    ]
    assert ctx.eventos[-1].id_registro == "801"


def test_caj07_doble_custodia_409(ctx: Contexto) -> None:
    preparar_dotacion(ctx)
    r = ctx.cliente.post(
        f"{BASE}/jornadas/55/dotaciones",
        json={**CUERPO_DOTACION, "autorizadoPor": ID_CAJERO},
    )
    assert r.status_code == 409
    assert code(r) == "DOBLE_CUSTODIA_VIOLADA"
    assert not ctx.llamadas["registrar_dotacion"]


def test_caj07_supervisor_debe_autorizar_con_su_id(ctx: Contexto) -> None:
    preparar_dotacion(ctx)
    ctx.como("SUPERVISOR", id_interno=ID_SUPERVISOR)
    r = ctx.cliente.post(
        f"{BASE}/jornadas/55/dotaciones", json={**CUERPO_DOTACION, "autorizadoPor": 99}
    )
    assert r.status_code == 422
    assert code(r) == "AUTORIZADOR_NO_COINCIDE"
    ok = ctx.cliente.post(f"{BASE}/jornadas/55/dotaciones", json=CUERPO_DOTACION)
    assert ok.status_code == 201


@pytest.mark.parametrize(
    ("numero", "status"),
    [(51014, 422), (51006, 409), (51010, 422), (51005, 404), (51013, 409)],
)
def test_caj07_errores_del_procedimiento(
    ctx: Contexto, numero: int, status: int
) -> None:
    preparar_dotacion(ctx)
    ctx.fake("registrar_dotacion", error_bd(numero))
    r = ctx.cliente.post(f"{BASE}/jornadas/55/dotaciones", json=CUERPO_DOTACION)
    assert r.status_code == status
    assert code(r) == f"DB_{numero}"
    assert "EXEC" not in r.text
    assert ctx.resultado_auditoria() == "Fallido"


def test_caj07_jornada_no_abierta_409(ctx: Contexto) -> None:
    preparar_dotacion(ctx)
    ctx.fake("obtener_jornada", jornada(Estado="CERRADA"))
    r = ctx.cliente.post(f"{BASE}/jornadas/55/dotaciones", json=CUERPO_DOTACION)
    assert r.status_code == 409
    assert code(r) == "JORNADA_NO_ABIERTA"


def test_caj07_sin_calendario_contable_500(ctx: Contexto) -> None:
    preparar_dotacion(ctx)
    ctx.fake("id_fecha_contable", None)
    r = ctx.cliente.post(f"{BASE}/jornadas/55/dotaciones", json=CUERPO_DOTACION)
    assert r.status_code == 500
    assert code(r) == "CALENDARIO_SIN_FECHA"


@pytest.mark.parametrize(
    "cambio",
    [
        {"desglose": []},
        {"desglose": [{"idDenominacion": 1, "cantidad": 1}] * 2},
        {"desglose": [{"idDenominacion": 1, "cantidad": 0}]},
        {"tipoDotacion": "OTRA"},
    ],
)
def test_caj07_validacion_400(ctx: Contexto, cambio: dict[str, Any]) -> None:
    r = ctx.cliente.post(
        f"{BASE}/jornadas/55/dotaciones", json={**CUERPO_DOTACION, **cambio}
    )
    assert r.status_code == 400


def test_desglose_json_formato_del_procedimiento() -> None:
    texto = desglose_json([Desglose(id_denominacion=3, cantidad=20)])
    assert texto == '[{"IdDenominacion": 3, "Cantidad": 20}]'


def test_validar_custodia() -> None:
    validar_custodia("CAJERO", actor=7, autorizado_por=9, id_cajero=7)
    validar_custodia("SUPERVISOR", actor=9, autorizado_por=9, id_cajero=7)
    with pytest.raises(HTTPException) as exc:
        validar_custodia("CAJERO", actor=7, autorizado_por=7, id_cajero=7)
    assert exc.value.detail["code"] == "DOBLE_CUSTODIA_VIOLADA"  # type: ignore[index]
    with pytest.raises(HTTPException) as exc:
        validar_custodia("SUPERVISOR", actor=9, autorizado_por=10, id_cajero=7)
    assert exc.value.status_code == 422


@pytest.mark.parametrize(
    ("numero", "status", "codigo"),
    [
        (51006, 409, "DB_51006"),
        (51014, 422, "DB_51014"),
        (51005, 404, "DB_51005"),
        (52002, 409, "CUENTA_NO_ACTIVA"),  # regresión: lo previo no cambia
        (51201, 422, "DB_51201"),
    ],
)
def test_traduccion_de_throw_caja(numero: int, status: int, codigo: str) -> None:
    exc = traducir_error_bd(
        DBAPIError("EXEC", None, Exception(f"Texto ({numero}) (SQLExecDirectW)"))
    )
    assert exc.status_code == status
    assert exc.detail["code"] == codigo  # type: ignore[index]


class _CursorFalso:
    """Simula pyodbc: un conjunto del SP y luego el SELECT de las salidas."""

    def __init__(
        self, conjuntos: list[tuple[list[str], list[tuple[Any, ...]]]]
    ) -> None:
        self._conjuntos = conjuntos
        self._i = 0
        self.ejecutado: tuple[str, tuple[Any, ...]] | None = None
        self.cerrado = False

    @property
    def description(self) -> list[tuple[str]] | None:
        columnas = self._conjuntos[self._i][0]
        return [(c,) for c in columnas] if columnas else None

    def execute(self, sql: str, parametros: tuple[Any, ...]) -> None:
        self.ejecutado = (sql, parametros)

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self._conjuntos[self._i][1]

    def nextset(self) -> bool:
        self._i += 1
        return self._i < len(self._conjuntos)

    def close(self) -> None:
        self.cerrado = True


class _ErrorDbapi(Exception):
    pass


def _conexion(cursor: Any) -> MagicMock:
    conn = MagicMock()
    conn.connection.cursor.return_value = cursor
    conn.dialect.loaded_dbapi.Error = _ErrorDbapi
    return conn


def test_ejecutar_con_salidas_toma_el_ultimo_resultado() -> None:
    cursor = _CursorFalso(
        [
            (["Interno"], [(1,)]),
            ([], []),
            (["IdDotacionCaja", "BovedaBajoMinimo"], [(5, True)]),
        ]
    )
    salida = ejecutar_con_salidas(_conexion(cursor), "EXEC x ?", [10])
    assert salida == {"IdDotacionCaja": 5, "BovedaBajoMinimo": True}
    assert cursor.ejecutado == ("EXEC x ?", (10,))
    assert cursor.cerrado


def test_ejecutar_con_salidas_envuelve_el_throw() -> None:
    class _CursorQueFalla(_CursorFalso):
        def execute(self, sql: str, parametros: tuple[Any, ...]) -> None:
            raise _ErrorDbapi("Mensaje (51007) (SQLExecDirectW)")

    cursor = _CursorQueFalla([([], [])])
    with pytest.raises(DBAPIError) as exc:
        ejecutar_con_salidas(_conexion(cursor), "EXEC x ?", [1])
    assert traducir_error_bd(exc.value).status_code == 409
    assert cursor.cerrado


def test_ejecutar_con_salidas_sin_resultado_falla() -> None:
    with pytest.raises(RuntimeError):
        ejecutar_con_salidas(_conexion(_CursorFalso([([], [])])), "EXEC x", [])
