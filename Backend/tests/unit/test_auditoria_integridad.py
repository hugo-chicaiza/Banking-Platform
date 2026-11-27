"""E8-02 · Integridad y archivo de la bitácora (#413).

La cadena, la detección de alteraciones y el archivo se ensayaron contra SQL Server (Azure) en una
transacción revertida (backups/<fecha>_E8-02); aquí se cubren la API, la alerta, las tareas y que la
migración deje la base negando lo que los criterios piden.
"""

import inspect
import logging
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.modules.auditoria import integridad
from app.modules.auditoria.integridad import Verificacion
from tests.sesion import simular_sesion, usuario_con_roles

BASE = "/api/v1/auditoria/verificaciones"
MIGRACION = (
    Path(__file__).resolve().parents[2]
    / "migrations/seguridad/202611271100_auditoria_integridad.up.sql"
).read_text(encoding="utf-8")


def _verificacion(**cambios: Any) -> Verificacion:
    datos: dict[str, Any] = {
        "id_verificacion": 9,
        "secuencia_desde": 1,
        "secuencia_hasta": 40,
        "resultado": "Integra",
        "primera_rota": None,
        "ejecutada_por": 1,
        "fecha_utc": datetime(2026, 11, 27, 6, tzinfo=UTC),
    }
    return Verificacion(**(datos | cambios))


@pytest.fixture
def http() -> Iterator[TestClient]:
    yield TestClient(app)
    app.dependency_overrides.clear()


def _sesion(*roles: str) -> None:
    simular_sesion(app, replace(usuario_con_roles(*roles), id_interno=1))


class _Motor:
    """get_engine falso: `begin()`/`connect()` devuelven la misma conexión simulada."""

    def __init__(self, conn: Any) -> None:
        self.conn = conn

    def begin(self) -> Any:
        return self

    connect = begin

    def __enter__(self) -> Any:
        return self.conn

    def __exit__(self, *_: object) -> None:
        return None


# --- API -------------------------------------------------------------------------------


def test_verificar_sin_rango_400(http):
    _sesion("AUDITOR")
    r = http.post(BASE, json={})
    assert r.status_code == 400
    assert r.json()["code"] == "RANGO_REQUERIDO"


def test_verificar_rango_mayor_a_un_anio_422(http):
    _sesion("AUDITOR")
    r = http.post(BASE, json={"desde": "2025-01-01", "hasta": "2026-11-26"})
    assert r.status_code == 422
    assert r.json()["code"] == "RANGO_EXCEDIDO"


def test_verificar_devuelve_integra_y_quien_la_pidio(http, monkeypatch):
    _sesion("AUDITOR")
    llamadas: list[tuple[date, date, int | None]] = []
    monkeypatch.setattr(
        integridad,
        "verificar",
        lambda d, h, por: llamadas.append((d, h, por)) or _verificacion(),
    )
    r = http.post(BASE, json={"desde": "2026-11-01", "hasta": "2026-11-26"})
    assert r.status_code == 201
    assert r.json()["resultado"] == "Integra"
    assert r.headers["cache-control"] == "no-store"
    assert llamadas == [(date(2026, 11, 1), date(2026, 11, 26), 1)]


def test_verificar_rango_sin_cadena_422(http, monkeypatch):
    _sesion("ADMIN")
    monkeypatch.setattr(integridad, "verificar", lambda *a: None)
    r = http.post(BASE, json={"desde": "2026-01-01", "hasta": "2026-01-02"})
    assert r.status_code == 422
    assert r.json()["code"] == "RANGO_SIN_REGISTROS"


def test_cajero_no_verifica_ni_lista(http):
    _sesion("CAJERO")
    assert (
        http.post(BASE, json={"desde": "2026-11-01", "hasta": "2026-11-02"}).status_code
        == 403
    )
    assert http.get(BASE).status_code == 403


def test_listar_verificaciones_queda_registrado(http, monkeypatch, eventos_auditados):
    _sesion("SUPERVISOR")
    rota = _verificacion(
        id_verificacion=10, resultado="Rota", primera_rota=7, ejecutada_por=None
    )
    monkeypatch.setattr(integridad, "listar", lambda page, size: ([rota], 1))
    r = http.get(BASE, params={"page": 1, "pageSize": 5})
    assert r.status_code == 200
    assert r.json()["items"][0]["primeraRota"] == 7
    assert r.json()["items"][0]["ejecutadaPor"] is None
    assert [e.accion for e in eventos_auditados] == ["AUD_LECTURA"]


# --- Verificación y alerta (AC2) --------------------------------------------------------


def _verificar_con(monkeypatch, rota: int | None) -> Verificacion | None:
    conn = MagicMock()
    conn.execute.return_value.one.return_value = (
        5,
        1,
        40,
        "Rota" if rota else "Integra",
        rota,
        None,
        datetime(2026, 11, 27, 6),
    )
    monkeypatch.setattr(integridad, "get_engine", lambda _: _Motor(conn))
    monkeypatch.setattr(integridad, "rango_de_secuencias", lambda c, d, h: (1, 40))
    monkeypatch.setattr(integridad, "primera_rota", lambda c, d, h: rota)
    return integridad.verificar(date(2026, 11, 26), date(2026, 11, 26), None)


def test_ruptura_crea_alerta_y_evento(monkeypatch, eventos_auditados, caplog):
    caplog.set_level(logging.ERROR)
    resultado = _verificar_con(monkeypatch, 7)
    assert resultado is not None and resultado.primera_rota == 7
    assert "AUD_INTEGRIDAD_ROTA" in caplog.text and "primera_rota=7" in caplog.text
    [evento] = eventos_auditados
    assert (evento.accion, evento.resultado, evento.canal) == (
        "AUD_INTEGRIDAD_ROTA",
        "Fallido",
        "SISTEMA",
    )


def test_cadena_integra_no_alerta(monkeypatch, eventos_auditados, caplog):
    caplog.set_level(logging.ERROR)
    assert _verificar_con(monkeypatch, None) is not None
    assert not eventos_auditados and "AUD_INTEGRIDAD_ROTA" not in caplog.text


def test_tarea_nocturna_verifica_el_dia_anterior_de_ecuador(monkeypatch):
    dias: list[date] = []
    monkeypatch.setattr(integridad, "_ayer", lambda: date(2026, 11, 26))
    monkeypatch.setattr(
        integridad,
        "verificar",
        lambda d, h, por: (
            dias.append(d) or _verificacion(resultado="Rota", primera_rota=3)
        ),
    )
    conteo = integridad.tarea_verificar()
    assert dias == [date(2026, 11, 26)]
    assert (conteo.procesados, conteo.errores) == (40, 1)


# --- Archivo anual (AC3) ----------------------------------------------------------------


def test_archivo_por_lotes_y_evento(monkeypatch, eventos_auditados):
    lotes = iter([integridad.LOTE_ARCHIVO, 5])
    conn = MagicMock()
    conn.execute.side_effect = lambda *a, **k: MagicMock(scalar_one=lambda: next(lotes))
    monkeypatch.setattr(integridad, "get_engine", lambda _: _Motor(conn))
    monkeypatch.setattr(integridad.general, "valor", lambda c, clave, f: 2)
    conteo = integridad.tarea_archivar()
    assert conteo.procesados == integridad.LOTE_ARCHIVO + 5
    [evento] = eventos_auditados
    assert (
        evento.accion == "AUD_ARCHIVO"
        and f"={integridad.LOTE_ARCHIVO + 5} " in evento.descripcion
    )


def test_visor_lee_activa_y_archivo():
    from app.modules.auditoria import repository

    assert "FROM Auditoria.vw_Bitacora AS a" in repository._ORIGEN
    assert "vw_EventoDetalle" in repository._BUSQUEDA
    assert "FROM Auditoria.AuditoriaArchivo" in MIGRACION


# --- La base niega (AC1, AC4); verificado en Azure con el ensayo ---------------------------


def test_migracion_niega_modificar_bitacora_y_logtransacciones():
    assert (
        "trg_Auditoria_SoloInsercion ON Auditoria.Auditoria AFTER UPDATE, DELETE"
        in MIGRACION
    )
    assert "IF EXISTS (SELECT 1 FROM inserted)" in MIGRACION  # todo UPDATE se rechaza
    assert (
        "trg_LogTransacciones_Congelada ON Seguridad.LogTransacciones INSTEAD OF INSERT, UPDATE, DELETE"
        in MIGRACION
    )
    for tabla in ("AuditoriaArchivo", "EventoDetalleArchivo", "VerificacionIntegridad"):
        assert f"ON Auditoria.{tabla} AFTER UPDATE, DELETE" in MIGRACION


def test_escritores_usan_el_procedimiento_encadenado():
    from app.core.security import audit
    from app.modules.aprobaciones import relevo

    for modulo in (audit, relevo):
        fuente = inspect.getsource(modulo)
        assert "EXEC Auditoria.usp_RegistrarEvento" in fuente
        assert (
            "INSERT Auditoria.Auditoria" not in fuente
            and "INSERT INTO Auditoria.Auditoria" not in fuente
        )
