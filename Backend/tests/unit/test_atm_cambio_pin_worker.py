"""Ejecutor acotado: pruebas sin SQL ni conexiones externas."""

import json
from contextlib import contextmanager, nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock
from uuid import uuid4

import pyodbc
import pytest
from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError

from app.core.config.settings import Settings
from app.modules.atm import cambio_pin_recovery as cli
from app.modules.atm import cambio_pin_worker as worker
from app.modules.atm.cambio_pin_service import (
    RecuperacionNoConfirmada,
    error_transitorio,
)


@pytest.fixture
def job(monkeypatch):
    op = str(uuid4())
    conn = Mock()

    @contextmanager
    def lease():
        yield conn

    monkeypatch.setattr(worker, "lease", lease)
    monkeypatch.setattr(worker, "comprobar_lease", Mock())
    monkeypatch.setattr(worker, "pendientes", Mock(return_value=([op], 0)))
    monkeypatch.setattr(worker, "elegible", Mock(return_value=True))
    recuperar = Mock()
    auditoria = Mock(return_value=True)
    monkeypatch.setattr(worker, "recuperar_cambio_pin", recuperar)
    monkeypatch.setattr(worker, "observar", auditoria)
    monkeypatch.setattr(worker, "sleep", Mock())
    return SimpleNamespace(op=op, conn=conn, recuperar=recuperar, auditoria=auditoria)


def test_deshabilitado_no_conecta(monkeypatch):
    monkeypatch.setattr(
        worker, "get_settings", lambda: SimpleNamespace(atm_pin_recovery_enabled=False)
    )
    motor = Mock(side_effect=AssertionError("No conectar"))
    monkeypatch.setattr(worker, "get_engine", motor)
    assert worker.ejecutar_configurado() == 0
    motor.assert_not_called()


def test_lote_termina_y_pasa_ventana_al_coordinador(job):
    assert worker.ejecutar_lote(worker.Politica()) == 0
    job.recuperar.assert_called_once_with(job.op, max_edad_segundos=1800)


def test_reintentos_transitorios_solo_dentro_de_la_ejecucion(job):
    job.recuperar.side_effect = [
        RecuperacionNoConfirmada(reintentable=True),
        RecuperacionNoConfirmada(reintentable=True),
        None,
    ]
    assert worker.ejecutar_lote(worker.Politica()) == 0
    assert job.recuperar.call_count == 3


def test_limite_no_es_acumulado_y_auditoria_no_lo_controla(job):
    job.recuperar.side_effect = RecuperacionNoConfirmada(reintentable=True)
    assert worker.ejecutar_lote(worker.Politica(intentos=2)) == 1
    assert worker.ejecutar_lote(worker.Politica(intentos=2)) == 1
    assert job.recuperar.call_count == 4


def test_inconsistencia_no_se_reintenta_y_no_se_loguea_detalle(job, caplog):
    secreto = "SECRETOS_NO_PERMITIDOS"
    job.recuperar.side_effect = HTTPException(503, secreto)
    assert worker.ejecutar_lote(worker.Politica()) == 1
    assert job.recuperar.call_count == 1
    assert "INCONSISTENTE" in caplog.text
    assert secreto not in caplog.text


def test_vencidas_generan_alerta_sin_recuperarlas(job, monkeypatch, caplog):
    monkeypatch.setattr(worker, "pendientes", lambda *a: ([], 3))
    assert worker.ejecutar_lote(worker.Politica()) == 1
    job.recuperar.assert_not_called()
    assert "EXPIRED_PENDING count=3" in caplog.text


def test_ya_no_elegible_no_se_procesa(job, monkeypatch):
    monkeypatch.setattr(worker, "elegible", lambda *a: False)
    assert worker.ejecutar_lote(worker.Politica()) == 0
    job.recuperar.assert_not_called()


def test_presupuesto_blando_no_inicia_nuevas_operaciones(job, monkeypatch):
    reloj = iter([0, 46, 46])
    monkeypatch.setattr(worker, "monotonic", lambda: next(reloj))
    assert worker.ejecutar_lote(worker.Politica()) == 0
    job.recuperar.assert_not_called()


def test_no_duerme_ni_reintenta_si_agota_presupuesto(job, monkeypatch):
    reloj = iter([0, 0, 44.5, 46])
    monkeypatch.setattr(worker, "monotonic", lambda: next(reloj))
    job.recuperar.side_effect = RecuperacionNoConfirmada(reintentable=True)
    assert worker.ejecutar_lote(worker.Politica()) == 1
    assert job.recuperar.call_count == 1


def test_lease_ocupada_sale_sin_trabajar(job, monkeypatch):
    @contextmanager
    def ocupada():
        yield None

    monkeypatch.setattr(worker, "lease", ocupada)
    assert worker.ejecutar_lote(worker.Politica()) == 0
    job.recuperar.assert_not_called()


def test_lease_perdida_detiene_ejecucion(job, monkeypatch):
    monkeypatch.setattr(
        worker, "comprobar_lease", Mock(side_effect=worker.LeasePerdida())
    )
    assert worker.ejecutar_lote(worker.Politica()) == 1
    job.recuperar.assert_not_called()


def test_lease_no_permite_pool_odbc_inseguro(monkeypatch):
    monkeypatch.setattr(pyodbc, "pooling", True)
    motor = Mock(side_effect=AssertionError("No conectar"))
    monkeypatch.setattr(worker, "get_engine", motor)
    with pytest.raises(worker.LeasePerdida), worker.lease():
        pytest.fail("No debe obtener una sesion con pooling inferior activo")
    motor.assert_not_called()


@pytest.mark.parametrize("al_adquirir", [True, False])
def test_lease_ambigua_descarta_conexion(monkeypatch, al_adquirir):
    monkeypatch.setattr(pyodbc, "pooling", False)
    conn = MagicMock()
    conn.invalidated = False
    engine = MagicMock()
    engine.connect.return_value.__enter__.return_value = conn
    monkeypatch.setattr(worker, "get_engine", lambda *a: engine)
    monkeypatch.setattr(worker, "sesion_sql_acotada", lambda *a: nullcontext())
    respuestas = (
        [SQLAlchemyError("Error sintetico")]
        if al_adquirir
        else [{"Resultado": 0}, RuntimeError("Sin resultado")]
    )
    monkeypatch.setattr(worker, "ejecutar_con_salidas", Mock(side_effect=respuestas))
    with pytest.raises(worker.LeasePerdida), worker.lease():
        pass
    conn.invalidate.assert_called_once()


def test_auditoria_fallida_no_se_usa_como_presupuesto(job):
    job.auditoria.return_value = False
    assert worker.ejecutar_lote(worker.Politica()) == 1
    job.recuperar.assert_called_once()


def test_auditoria_identifica_proceso_sin_suplantar_workos(monkeypatch):
    guardar = Mock()
    monkeypatch.setattr(worker.audit, "_persistir", guardar)
    assert worker.observar(str(uuid4()), "ATM06_REC_OK", "OK")
    evento = guardar.call_args.args[0]
    assert evento.usuario is None and evento.roles == ""
    assert evento.descripcion == "ejecutor=ATM06_WEBJOB; resultado=OK"
    assert evento.resultado == "Exitoso"


def test_errores_inesperados_no_exponen_secretos(job, caplog):
    job.recuperar.side_effect = RuntimeError("PIN_BLOCK_Y_JWT_SECRETO")
    assert worker.ejecutar_lote(worker.Politica()) == 1
    assert "UNEXPECTED_FAILURE" in caplog.text
    assert "PIN_BLOCK_Y_JWT_SECRETO" not in caplog.text


@pytest.mark.parametrize(
    "valores",
    [
        {"min_edad": 40, "max_edad": 30},
        {"intentos": 0},
        {"lote": 201},
        {"presupuesto": 0},
        {"espera": -1},
    ],
)
def test_configuracion_invalida_rechazada(valores):
    with pytest.raises(ValueError):
        worker.Politica(**valores)


@pytest.mark.parametrize(
    "estado,codigo,esperado",
    [
        ("08S01", 0, True),
        ("HYT00", 0, True),
        ("40001", 1205, True),
        ("HY000", 1222, True),
        ("42000", 229, False),
        ("42S02", 208, False),
    ],
)
def test_clasificacion_sql_sin_exponer_mensajes(estado, codigo, esperado):
    assert (
        error_transitorio(
            pyodbc.OperationalError(estado, f"Error sintetico ({codigo})")
        )
        is esperado
    )


def test_configuracion_settings_por_defecto():
    settings = Settings.model_construct()
    assert not settings.atm_pin_recovery_enabled
    assert worker.Politica.desde_settings(settings) == worker.Politica()


def test_cli_mantiene_modo_manual_y_modo_lote(monkeypatch):
    monkeypatch.setattr(pyodbc, "pooling", True)
    monkeypatch.setattr(cli, "get_settings", lambda: SimpleNamespace(log_level="INFO"))
    monkeypatch.setattr(cli, "configurar_logging", lambda *a: None)
    monkeypatch.setattr(worker, "ejecutar_configurado", lambda: 0)
    monkeypatch.setattr("sys.argv", ["recuperar", "--pendientes"])
    assert cli.main() == 0
    assert pyodbc.pooling is False
    recuperar = Mock()
    monkeypatch.setattr(cli, "recuperar_cambio_pin", recuperar)
    op = str(uuid4())
    monkeypatch.setattr("sys.argv", ["recuperar", "--operacion", op])
    assert cli.main() == 0
    recuperar.assert_called_once_with(op)


def test_paquete_webjob_sin_scheduler_en_fastapi():
    base = (
        Path(__file__).resolve().parents[2] / "App_Data/jobs/triggered/atm06-recovery"
    )
    config = json.loads((base / "settings.job").read_text())
    assert config["schedule"] == "0 * * * * *"
    assert config["is_singleton"] is True
    script = (base / "run.sh").read_bytes()
    assert script.startswith(b"#!/bin/bash\n") and b"\r\n" not in script
    assert b"--pendientes" in script and b"pip install" not in script
