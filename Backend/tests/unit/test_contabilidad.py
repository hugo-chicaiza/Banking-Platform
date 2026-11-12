"""Pruebas unitarias de CON-01 y CON-02 (AC-02 · fecha contable).

No requieren base de datos: se monkeypatcha el repositorio.
"""

from datetime import date, datetime, time
from decimal import Decimal
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


# ---------------------------------------------------------------------------
# CON-03 · GET /contabilidad/cuentas-contables (API Contract Ready)
# ---------------------------------------------------------------------------

_CUENTAS = "/api/v1/contabilidad/cuentas-contables"


def test_con03_contrato_en_el_openapi():
    spec = app.openapi()
    operacion = spec["paths"][_CUENTAS]["get"]

    assert operacion["operationId"] == "CON03"
    assert operacion["x-roles"] == ["CONTADOR", "AUDITOR", "ADMIN"]
    parametros = {p["name"]: p for p in operacion["parameters"]}
    assert set(parametros) == {"q", "imputable"}
    assert not parametros["q"]["required"]
    assert not parametros["imputable"]["required"]
    esquema = operacion["responses"]["200"]["content"]["application/json"]["schema"]
    assert esquema["type"] == "array"
    assert esquema["items"]["$ref"].endswith("/CuentaContable")
    propiedades = spec["components"]["schemas"]["CuentaContable"]["properties"]
    assert set(propiedades) == {
        "idCuentaContable",
        "codigoCuenta",
        "nombreCuenta",
        "naturaleza",
        "tipoCuenta",
        "idCuentaSuperior",
        "esImputable",
        "saldo",
        "estado",
    }


def test_con03_cuenta_se_serializa_como_el_contrato():
    from app.modules.contabilidad.schemas import CuentaContable

    cuenta = CuentaContable(
        id_cuenta_contable=1,
        codigo_cuenta="COD01",
        nombre_cuenta="nombreCuenta",
        naturaleza="DEUDORA",
        tipo_cuenta="Ahorros",
        id_cuenta_superior=None,
        es_imputable=True,
        saldo=Decimal("150.00"),
        estado="Activo",
    )

    assert cuenta.model_dump(mode="json", by_alias=True) == {
        "idCuentaContable": 1,
        "codigoCuenta": "COD01",
        "nombreCuenta": "nombreCuenta",
        "naturaleza": "DEUDORA",
        "tipoCuenta": "Ahorros",
        "idCuentaSuperior": None,
        "esImputable": True,
        "saldo": 150.0,
        "estado": "Activo",
    }


def _cuenta(**cambios):
    fila = {
        "id_cuenta_contable": 1,
        "codigo_cuenta": "1",
        "nombre_cuenta": "ACTIVO",
        "naturaleza": "DEUDORA",
        "tipo_cuenta": "ACTIVO",
        "id_cuenta_superior": None,
        "es_imputable": False,
        "saldo": Decimal("150.00"),
        "estado": True,
    }
    return {**fila, **cambios}


@pytest.mark.parametrize("rol", ["CONTADOR", "AUDITOR", "ADMIN"])
def test_con03_roles_permitidos_reciben_el_plan_de_cuentas(client, monkeypatch, rol):
    from tests.sesion import usuario_con_roles

    simular_sesion(app, usuario_con_roles(rol))
    monkeypatch.setattr(
        repository, "listar_cuentas_contables", lambda conn, q, i: [_cuenta()]
    )

    r = client.get(_CUENTAS)

    assert r.status_code == 200
    assert r.json() == [
        {
            "idCuentaContable": 1,
            "codigoCuenta": "1",
            "nombreCuenta": "ACTIVO",
            "naturaleza": "DEUDORA",
            "tipoCuenta": "ACTIVO",
            "idCuentaSuperior": None,
            "esImputable": False,
            "saldo": 150.0,
            "estado": "Activo",
        }
    ]


def test_con03_estado_inactivo_y_filtros_llegan_al_repositorio(client, monkeypatch):
    recibido = {}

    def _fn(conn, q, imputable):
        recibido.update(q=q, imputable=imputable)
        return [_cuenta(estado=False, es_imputable=True, id_cuenta_superior=1)]

    monkeypatch.setattr(repository, "listar_cuentas_contables", _fn)

    r = client.get(_CUENTAS, params={"q": "caja", "imputable": "true"})

    assert recibido == {"q": "caja", "imputable": True}
    assert r.status_code == 200
    assert r.json()[0]["estado"] == "Inactivo"
    assert r.json()[0]["idCuentaSuperior"] == 1


def test_con03_sin_filtros_y_sin_resultados_devuelve_lista_vacia(client, monkeypatch):
    recibido = {}

    def _fn(conn, q, imputable):
        recibido.update(q=q, imputable=imputable)
        return []

    monkeypatch.setattr(repository, "listar_cuentas_contables", _fn)

    r = client.get(_CUENTAS)

    assert recibido == {"q": None, "imputable": None}
    assert r.status_code == 200
    assert r.json() == []


def test_con03_rol_fuera_de_la_tarea_recibe_403(client):
    from tests.sesion import usuario_con_roles

    simular_sesion(app, usuario_con_roles("ASESOR"))

    r = client.get(_CUENTAS)

    assert r.status_code == 403
    assert r.json()["code"] == "SIN_PERMISO"


def test_con03_parametro_desconocido_o_repetido_es_400(client):
    desconocido = client.get(_CUENTAS, params={"nivel": "1"})
    repetido = client.get(f"{_CUENTAS}?q=a&q=b")

    for r in (desconocido, repetido):
        assert r.status_code == 400
        assert r.json()["code"] == "PARAMETRO_INVALIDO"


@pytest.mark.parametrize(
    "consulta",
    ["q=", f"q={'x' * 101}", "imputable=quizas"],
)
def test_con03_valores_invalidos_son_400(client, consulta):
    r = client.get(f"{_CUENTAS}?{consulta}")

    assert r.status_code == 400
