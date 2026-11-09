"""Reloj de Ecuador y parámetros SQL de AC-02, sin conectar a una base."""

from datetime import datetime
from typing import cast
from unittest.mock import MagicMock, Mock

import pytest

from app.modules.caja import repository as caja
from app.modules.contabilidad import service as contabilidad
from app.modules.transacciones import repository as transacciones


@pytest.mark.parametrize(
    ("entrada", "local"),
    [
        ("2026-11-06T23:59:59+00:00", "2026-11-06T18:59:59"),
        ("2026-11-07T00:00:00+00:00", "2026-11-06T19:00:00"),
    ],
)
def test_caja_consulta_la_funcion_sql_con_hora_ecuatoriana(entrada, local):
    conn = MagicMock()
    conn.execute.return_value.mappings.return_value.first.return_value = {
        "id_fecha_contable": 9
    }

    assert caja.id_fecha_contable(conn, datetime.fromisoformat(entrada)) == 9

    sql, parametros = conn.execute.call_args.args
    assert "Contabilidad.fn_IdFechaContable" in str(sql)
    assert "GETDATE" not in str(sql)
    assert parametros == {"fecha_hora": datetime.fromisoformat(local)}


def test_caja_sin_instante_usa_el_reloj_de_ecuador(monkeypatch):
    instante = datetime(2026, 11, 6, 19)
    monkeypatch.setattr(contabilidad, "ahora_ecuador", lambda: instante)
    conn = MagicMock()
    conn.execute.return_value.mappings.return_value.first.return_value = {
        "id_fecha_contable": 9
    }

    assert caja.id_fecha_contable(conn) == 9
    assert conn.execute.call_args.args[1] == {"fecha_hora": instante}


def test_caja_sin_calendario_conserva_el_error_operativo():
    from fastapi import HTTPException

    conn = MagicMock()
    conn.execute.return_value.mappings.return_value.first.return_value = {
        "id_fecha_contable": None
    }
    with pytest.raises(HTTPException) as error:
        caja.id_fecha_contable(conn, datetime(2099, 1, 1))
    assert error.value.status_code == 500
    detalle = cast(dict[str, str], error.value.detail)
    assert detalle["code"] == "CALENDARIO_SIN_FECHA"


def test_transaccion_guarda_el_instante_proporcionado_por_el_servicio():
    instante = datetime(2026, 11, 6, 19)
    conn = MagicMock()
    conn.execute.return_value.first.return_value = (5001,)
    datos = {"fecha_hora": instante, "id_fecha_contable": 9}

    assert transacciones.insertar_transaccion(conn, datos) == 5001

    sql, parametros = conn.execute.call_args.args
    assert "DECLARE @Ahora datetime2 = :fecha_hora" in str(sql)
    assert "GETDATE" not in str(sql)
    assert parametros["fecha_hora"] == instante


def test_movimiento_caja_usa_la_hora_de_su_transaccion():
    conn = MagicMock()
    transacciones.insertar_movimiento_caja(conn, 5001, 55, "001", 2, 100, None, 777, 9)
    sql, parametros = conn.execute.call_args.args
    assert "SELECT FechaHoraSistema FROM Transacciones.Transaccion" in str(sql)
    assert "GETDATE" not in str(sql)
    assert parametros["id_transaccion"] == 5001


@pytest.mark.parametrize("explicita", [True, False])
def test_autorizacion_recibe_hora_ecuatoriana_como_parametro(monkeypatch, explicita):
    instante = datetime(2026, 11, 6, 19)
    monkeypatch.setattr(transacciones, "ahora_ecuador", lambda: instante)
    ejecutar = Mock(return_value={"CodigoRespuesta": "00"})
    monkeypatch.setattr(transacciones, "ejecutar_con_salidas", ejecutar)
    conn = MagicMock()

    transacciones.autorizar_operacion(
        conn, 501, 4, "Retiro", 100, fecha_hora=instante if explicita else None
    )

    _, sql, parametros = ejecutar.call_args.args
    assert "GETDATE" not in sql
    assert parametros == (instante, 501, 4, "Retiro", 100)
