"""Pruebas unitarias de CON-01 y CON-02 (AC-02 · fecha contable).

No requieren base de datos: se monkeypatcha el repositorio.
"""

from datetime import date, datetime, time
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection

from app.core.database.db import cooperativa
from app.main import app
from app.modules.contabilidad import repository, service
from tests.sesion import simular_sesion


@pytest.fixture
def client():
    app.dependency_overrides[cooperativa] = lambda: None
    simular_sesion(app)
    yield TestClient(app)
    app.dependency_overrides.clear()


def _fila(**cambios):
    fila = {
        "id_fecha_contable": 2,
        "fecha": date(2026, 1, 2),
        "es_dia_contable": True,
        "es_feriado": False,
        "es_fin_de_semana": False,
        "hora_corte": time(19, 0),
    }
    return {**fila, **cambios}


# ---------------------------------------------------------------------------
# CON-01 · GET /contabilidad/fechas-contables/{fecha}
# ---------------------------------------------------------------------------


def test_con01_dia_habil(client, monkeypatch):
    monkeypatch.setattr(repository, "obtener_por_fecha", lambda conn, fecha: _fila())

    r = client.get("/api/v1/contabilidad/fechas-contables/2026-01-02")

    assert r.status_code == 200
    assert r.json() == {
        "idFechaContable": 2,
        "fecha": "2026-01-02",
        "esDiaContable": True,
        "esFeriado": False,
        "esFinDeSemana": False,
        "horaCorte": "19:00:00",
    }


def test_con01_feriado_no_es_dia_contable(client, monkeypatch):
    fila = _fila(
        id_fecha_contable=1,
        fecha=date(2026, 1, 1),
        es_dia_contable=False,
        es_feriado=True,
    )
    monkeypatch.setattr(repository, "obtener_por_fecha", lambda conn, fecha: fila)

    r = client.get("/api/v1/contabilidad/fechas-contables/2026-01-01")

    assert r.status_code == 200
    assert r.json()["esFeriado"] is True
    assert r.json()["esDiaContable"] is False


def test_con01_fin_de_semana(client, monkeypatch):
    fila = _fila(
        id_fecha_contable=3,
        fecha=date(2026, 1, 3),
        es_dia_contable=False,
        es_fin_de_semana=True,
    )
    monkeypatch.setattr(repository, "obtener_por_fecha", lambda conn, fecha: fila)

    r = client.get("/api/v1/contabilidad/fechas-contables/2026-01-03")

    assert r.status_code == 200
    assert r.json()["esFinDeSemana"] is True
    assert r.json()["esDiaContable"] is False


@pytest.mark.parametrize(
    "fecha", ["hoy", "2026-13-01", "2026-02-30", "20260102", "2026-1-2"]
)
def test_con01_fecha_invalida_400(client, monkeypatch, fecha):
    monkeypatch.setattr(repository, "obtener_por_fecha", lambda conn, f: _fila())

    r = client.get(f"/api/v1/contabilidad/fechas-contables/{fecha}")

    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "FECHA_INVALIDA"


def test_con01_fecha_no_cargada_404(client, monkeypatch):
    monkeypatch.setattr(repository, "obtener_por_fecha", lambda conn, fecha: None)

    r = client.get("/api/v1/contabilidad/fechas-contables/2099-01-01")

    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "FECHA_NO_ENCONTRADA"


# ---------------------------------------------------------------------------
# CON-02 · GET /contabilidad/fechas-contables/actual
# ---------------------------------------------------------------------------


def test_con02_actual_no_se_confunde_con_la_ruta_de_fecha(client, monkeypatch):
    """Si /actual quedara después de /{fecha}, 'actual' daría 400 FECHA_INVALIDA."""
    monkeypatch.setattr(
        service, "ahora_ecuador", lambda: datetime.fromisoformat("2026-01-02T10:00:00")
    )
    monkeypatch.setattr(repository, "id_fecha_contable", lambda conn, fh: 2)
    monkeypatch.setattr(repository, "obtener_por_id", lambda conn, i: _fila())

    r = client.get("/api/v1/contabilidad/fechas-contables/actual")

    assert r.status_code == 200
    assert r.json()["idFechaContable"] == 2


def test_con02_usa_la_hora_de_ecuador(client, monkeypatch):
    recibido = {}

    def _fn(conn, fecha_hora):
        recibido["fecha_hora"] = fecha_hora
        return 5

    ahora = datetime.fromisoformat("2026-01-02T19:30:00")
    monkeypatch.setattr(service, "ahora_ecuador", lambda: ahora)
    monkeypatch.setattr(repository, "id_fecha_contable", _fn)
    monkeypatch.setattr(
        repository,
        "obtener_por_id",
        lambda conn, i: _fila(id_fecha_contable=5, fecha=date(2026, 1, 5)),
    )

    r = client.get("/api/v1/contabilidad/fechas-contables/actual")

    assert recibido["fecha_hora"] == ahora
    assert r.status_code == 200
    assert r.json()["idFechaContable"] == 5
    assert r.json()["fecha"] == "2026-01-05"


def test_con02_calendario_sin_fechas_500(client, monkeypatch, caplog):
    monkeypatch.setattr(repository, "id_fecha_contable", lambda conn, fh: None)

    r = client.get("/api/v1/contabilidad/fechas-contables/actual")

    assert r.status_code == 500
    assert r.json()["detail"]["code"] == "CALENDARIO_SIN_FECHA"
    assert "ALERTA" in caplog.text


def test_con02_id_inexistente_500(client, monkeypatch):
    monkeypatch.setattr(repository, "id_fecha_contable", lambda conn, fh: 999)
    monkeypatch.setattr(repository, "obtener_por_id", lambda conn, i: None)

    r = client.get("/api/v1/contabilidad/fechas-contables/actual")

    assert r.status_code == 500
    assert r.json()["detail"]["code"] == "CALENDARIO_SIN_FECHA"


# ---------------------------------------------------------------------------
# Helpers reutilizables por otros módulos (AC-02)
# ---------------------------------------------------------------------------


def test_ahora_ecuador_es_naive_y_esta_en_utc_menos_5():
    ahora = service.ahora_ecuador()
    assert ahora.tzinfo is None
    assert service.ZONA_ECUADOR.utcoffset(None).total_seconds() == -5 * 3600


def test_resolver_id_fecha_contable_devuelve_el_id(monkeypatch):
    monkeypatch.setattr(repository, "id_fecha_contable", lambda conn, fh: 7)
    conn = Mock(spec=Connection)
    fecha_hora = datetime.fromisoformat("2026-01-07T09:00:00")
    assert service.resolver_id_fecha_contable(conn, fecha_hora) == 7


@pytest.mark.parametrize(
    ("instante", "hora_ecuador"),
    [
        ("2026-01-02T23:59:59+00:00", "2026-01-02T18:59:59"),
        ("2026-01-03T00:00:00+00:00", "2026-01-02T19:00:00"),
        ("2026-01-02T19:00:00-05:00", "2026-01-02T19:00:00"),
        ("2026-01-02T19:00:00", "2026-01-02T19:00:00"),
    ],
)
def test_resolver_envia_a_sql_la_hora_local_del_corte(
    monkeypatch, instante, hora_ecuador
):
    consulta = Mock(return_value=5)
    monkeypatch.setattr(repository, "id_fecha_contable", consulta)
    conn = Mock(spec=Connection)

    assert (
        service.resolver_id_fecha_contable(conn, datetime.fromisoformat(instante)) == 5
    )
    consulta.assert_called_once_with(conn, datetime.fromisoformat(hora_ecuador))
