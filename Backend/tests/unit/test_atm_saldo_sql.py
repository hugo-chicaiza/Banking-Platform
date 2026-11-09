"""Numeración y contratos SQL ATM-02; solo dobles, ninguna conexión real."""

from datetime import datetime
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.modules.atm import saldo_repository as repo
from app.modules.transacciones import numeracion
from app.modules.transacciones import repository as transacciones_repo


@pytest.mark.parametrize("tipo,codigo", [("Ahorro", "311000"), ("Corriente", "312000")])
@pytest.mark.parametrize("siguiente", [1, 999999])
def test_formatos_identificadores(tipo, codigo, siguiente, monkeypatch):
    monkeypatch.setattr(numeracion, "siguiente_secuencial", lambda *_: siguiente)
    monkeypatch.setattr(numeracion, "identificadores_ocupados", lambda *_: False)
    n = numeracion.numerar_consulta(MagicMock(), datetime(2026, 11, 8), tipo)
    assert n.secuencial == n.stan == f"{siguiente:06d}"
    assert n.rrn == f"261108{siguiente:06d}"
    assert n.numero_comprobante == f"ATM-20261108-{siguiente:06d}"
    assert n.codigo_procesamiento == codigo
    assert isinstance(n.rrn, str) and isinstance(n.stan, str)
    assert len(n.rrn) == 12 and len(n.stan) == 6


@pytest.mark.parametrize(
    "siguiente,codigo",
    [
        (None, "NUMERACION_NO_DISPONIBLE"),
        (1000000, "NUMERACION_AGOTADA"),
        (0, "NUMERACION_AGOTADA"),
    ],
)
def test_historico_incompatible_o_agotamiento_falla_cerrado(
    siguiente, codigo, monkeypatch
):
    monkeypatch.setattr(numeracion, "siguiente_secuencial", lambda *_: siguiente)
    with pytest.raises(HTTPException) as e:
        numeracion.numerar_consulta(MagicMock(), datetime(2026, 11, 8), "Ahorro")
    detalle = e.value.detail
    assert isinstance(detalle, dict)
    assert (
        e.value.status_code == 503 and cast(dict[str, Any], detalle)["code"] == codigo
    )


def test_agotamiento_del_dia_y_reinicio_al_cambiar_fecha(monkeypatch):
    conn = MagicMock()
    conn.execute.return_value.mappings.return_value.one.side_effect = [
        {"Maximo": 999998, "Invalidos": 0},
        {"Maximo": 999999, "Invalidos": 0},
        {"Maximo": 0, "Invalidos": 0},
    ]
    monkeypatch.setattr(numeracion, "identificadores_ocupados", lambda *_: False)
    dia = datetime(2026, 11, 8, 23, 59)
    ultimo = numeracion.numerar_consulta(conn, dia, "Ahorro")
    assert ultimo.stan == "999999"
    with pytest.raises(HTTPException):
        numeracion.numerar_consulta(conn, dia, "Ahorro")
    nuevo = numeracion.numerar_consulta(conn, datetime(2026, 11, 9), "Ahorro")
    assert nuevo.stan == "000001"
    assert ultimo.rrn != nuevo.rrn
    fechas = [c.args[1]["fecha"] for c in conn.execute.call_args_list]
    assert fechas == [dia.date(), dia.date(), datetime(2026, 11, 9).date()]


def test_colision_historica_rechaza_sin_generar_otra_numeracion(monkeypatch):
    siguiente = MagicMock(return_value=7)
    monkeypatch.setattr(numeracion, "siguiente_secuencial", siguiente)
    monkeypatch.setattr(numeracion, "identificadores_ocupados", lambda *_: True)
    with pytest.raises(HTTPException) as e:
        numeracion.numerar_consulta(MagicMock(), datetime(2026, 11, 8), "Ahorro")
    assert e.value.status_code == 503
    siguiente.assert_called_once()


def test_colisiones_globales_y_diarias_tienen_ambito_distinto():
    conn = MagicMock()
    conn.execute.return_value.scalar_one_or_none.return_value = None
    datos = {
        "comprobante": "ATM-20261109-000001",
        "rrn": "261109000001",
        "stan": "000001",
        "secuencial": "000001",
        "fecha": datetime(2026, 11, 9).date(),
    }
    assert numeracion.identificadores_ocupados(conn, datos) is False
    sql, parametros = conn.execute.call_args.args
    assert "NumeroComprobante = :comprobante OR RRN = :rrn" in str(sql)
    assert (
        "OR (FechaSistema = :fecha AND (STAN = :stan OR Secuencial = :secuencial))"
        in str(sql)
    )
    assert parametros == datos


@pytest.mark.parametrize("resultado", [-999, -3, -2, -1, 0, 1])
def test_applock_transaccional_con_espera_acotada(resultado):
    conn = MagicMock()
    conn.execute.return_value.scalar_one.return_value = resultado
    assert numeracion.bloquear_numeracion(conn) is (resultado >= 0)
    sql = str(conn.execute.call_args.args[0])
    assert "sys.sp_getapplock" in sql and "@LockTimeout = 5000" in sql
    assert "@LockOwner = 'Transaction'" in sql
    assert "IF @@TRANCOUNT = 0 BEGIN TRANSACTION" in sql
    conn.commit.assert_not_called()


@pytest.mark.parametrize("invalidos,esperado", [(0, 10), (1, None)])
def test_lectura_historico_no_ignora_formatos_ajenos(invalidos, esperado):
    conn = MagicMock()
    conn.execute.return_value.mappings.return_value.one.return_value = {
        "Maximo": 9,
        "Invalidos": invalidos,
    }
    dia = datetime(2026, 11, 8).date()
    assert numeracion.siguiente_secuencial(conn, dia) == esperado
    sql = str(conn.execute.call_args.args[0])
    assert "UPDLOCK, HOLDLOCK" in sql and "TRY_CONVERT" in sql
    assert "WHERE FechaSistema = :fecha" in sql
    assert conn.execute.call_args.args[1] == {"fecha": dia}
    assert "IdFechaContable" not in sql


def test_insert_consulta_no_invoca_movimientos_y_soporta_triggers():
    conn = MagicMock()
    conn.execute.return_value.scalar_one.return_value = 10
    datos = {"registro": "LAB000000001"}
    assert repo.insertar_consulta(conn, datos) == 10
    sql, parametros = conn.execute.call_args.args
    sql = str(sql)
    assert "OUTPUT INSERTED.IdTransaccion INTO @ids" in sql
    assert "'0200'" in sql and "'Consulta'" in sql
    assert "IdTarjeta, IdATM, IdCanal" in sql
    assert "UPDATE" not in sql and "EXEC" not in sql and "Asiento" not in sql
    assert parametros is datos
    conn.commit.assert_not_called()


def test_lectura_saldos_y_hora_en_la_misma_sentencia():
    conn = MagicMock()
    conn.execute.return_value.mappings.return_value.one_or_none.return_value = None
    assert repo.leer_cuenta(conn, 501) is None
    sql, parametros = conn.execute.call_args.args
    assert "c.Saldo, c.SaldoRetenido" in str(sql)
    assert "SYSDATETIMEOFFSET()" in str(sql) and "UPDLOCK, HOLDLOCK" in str(sql)
    assert parametros == {"id": 501}


def test_contexto_bloquea_terminal_y_tarjeta_en_orden_fijo():
    conn = MagicMock()
    repo.bloquear_contexto(conn, 7, 301)
    primera, segunda = conn.execute.call_args_list
    assert "FROM ATM.ATM WITH (UPDLOCK, HOLDLOCK)" in str(primera.args[0])
    assert "FROM Tarjeta.Tarjeta WITH (UPDLOCK, HOLDLOCK)" in str(segunda.args[0])
    assert primera.args[1] == {"id": 7} and segunda.args[1] == {"id": 301}


@pytest.mark.parametrize("ahora", [None, datetime(2026, 11, 8, 23, 59)])
def test_autorizador_reutilizado_con_reloj_opcional_de_ecuador(monkeypatch, ahora):
    ejecutar = MagicMock(return_value={"CodigoRespuesta": "00", "Comision": 0})
    monkeypatch.setattr(transacciones_repo, "ejecutar_con_salidas", ejecutar)
    hora_ecuador = datetime(2026, 11, 6, 19)
    monkeypatch.setattr(transacciones_repo, "ahora_ecuador", lambda: hora_ecuador)
    conn = MagicMock()
    transacciones_repo.autorizar_operacion(
        conn, 501, 2, "Consulta", 0, fecha_hora=ahora
    )
    conexion, sql, parametros = ejecutar.call_args.args
    assert conexion is conn
    assert parametros == (
        ahora if ahora is not None else hora_ecuador,
        501,
        2,
        "Consulta",
        0,
    )
    assert "@Ahora datetime2 = ?;" in sql and "GETDATE()" not in sql
