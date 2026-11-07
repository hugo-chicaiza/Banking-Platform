"""CAJ-07: integración contra BD de PRUEBA (rollback)."""

from collections.abc import Iterator

import pytest
from sqlalchemy import Connection

from app.modules.caja import repository as repo
from tests.caja_bd import (
    SIN_BD,
    conexion_de_prueba,
    definicion_de,
    parametros_de,
)

pytestmark = SIN_BD


@pytest.fixture
def conn() -> Iterator[Connection]:
    yield from conexion_de_prueba()


def test_procedimientos_tienen_la_firma_esperada(conn: Connection) -> None:
    esperado = {
        "Caja.usp_RegistrarDotacionCaja": [
            "@IdJornadaCaja",
            "@IdBoveda",
            "@AutorizadoPor",
            "@TipoDotacion",
            "@DesgloseJson",
            "@Observacion",
            "@IdFechaContable",
            "@IdDotacionCaja",
            "@IdMovimientoBoveda",
            "@BovedaBajoMinimo",
        ],
        "Caja.usp_RegistrarDevolucionCaja": [
            "@IdJornadaCaja",
            "@IdCuadreCaja",
            "@IdBovedaDestino",
            "@AutorizadoPor",
            "@DesgloseJson",
            "@Observacion",
            "@IdDevolucionCaja",
            "@IdMovimientoBoveda",
            "@SuperaLimiteMaximo",
        ],
        "Boveda.usp_RegistrarSeriesBilletes": [
            "@IdTransaccion",
            "@IdDenominacion",
            "@CantidadDeclarada",
            "@SeriesJson",
        ],
        "Transacciones.usp_AutorizarOperacion": [
            "@IdCuenta",
            "@IdCanal",
            "@TipoTransaccion",
            "@Monto",
            "@FechaHora",
            "@CodigoRespuesta",
            "@Mensaje",
            "@Comision",
        ],
        "Cuentas.usp_AplicarMovimientoCuenta": [
            "@IdTransaccion",
            "@IdCuenta",
            "@TipoMovimiento",
            "@RolCuenta",
            "@Monto",
            "@IdFechaContable",
            "@IdMovimiento",
        ],
    }
    for objeto, parametros in esperado.items():
        assert parametros_de(conn, objeto) == parametros, objeto


def test_fn_id_fecha_contable_firma(conn: Connection) -> None:
    """Desbloquea repo.id_fecha_contable: un parámetro de fecha/hora."""
    parametros = parametros_de(conn, "Contabilidad.fn_IdFechaContable")
    # El primero es el valor de retorno (name vacío) en funciones escalares
    assert len([p for p in parametros if p]) == 1, parametros
    assert repo.id_fecha_contable(conn) is not None


@pytest.mark.parametrize(
    ("objeto", "codigos"),
    [
        (
            "Caja.usp_RegistrarDotacionCaja",
            [51005, 51006, 51007, 51008, 51009, 51011, 51012, 51013],
        ),
    ],
)
def test_codigos_throw_caja(conn: Connection, objeto: str, codigos: list[int]) -> None:
    """Confirma que los códigos mapeados en _DB_ERRORES existen en el SP."""
    definicion = definicion_de(conn, objeto)
    assert definicion, f"Sin permiso VIEW DEFINITION sobre {objeto}"
    faltantes = [c for c in codigos if str(c) not in definicion]
    assert not faltantes, faltantes
