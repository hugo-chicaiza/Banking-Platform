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


# ---------------------------------------------------------------------------
# CON-04 · GET /contabilidad/asientos
# CON-05 · GET /contabilidad/asientos/{idAsiento}
# ---------------------------------------------------------------------------

_ASIENTOS = "/api/v1/contabilidad/asientos"


def _asiento(**cambios):
    fila = {
        "id_asiento_contable": 7,
        "numero_asiento": "001-2026-000007",
        "fecha_asiento": date(2026, 11, 4),
        "id_tipo_asiento": 1,
        "origen": "CAJA",
        "concepto": "Depósito en ventanilla",
        "total_debito": Decimal("150.00"),
        "total_credito": Decimal("150.00"),
        "estado": "CONTABILIZADO",
        "id_asiento_reversion": None,
        "id_agencia": "001",
    }
    return {**fila, **cambios}


def _movimiento(**cambios):
    fila = {
        "id_movimiento_contable": 10,
        "id_cuenta_contable": 3,
        "codigo_cuenta": "110105",
        "tipo_movimiento": "DEBITO",
        "monto": Decimal("150.00"),
        "id_transaccion": 9_000_000_001,
        "id_agencia": "001",
    }
    return {**fila, **cambios}


_ASIENTO_JSON = {
    "idAsientoContable": 7,
    "numeroAsiento": "001-2026-000007",
    "fechaAsiento": "2026-11-04",
    "idTipoAsiento": 1,
    "origen": "CAJA",
    "concepto": "Depósito en ventanilla",
    "totalDebito": 150.0,
    "totalCredito": 150.0,
    "estado": "CONTABILIZADO",
    "idAsientoReversion": None,
    "idAgencia": "001",
}

_NO_LLEGA = Mock(side_effect=AssertionError("no debe llegar al repositorio"))


def _capturar_listado(monkeypatch, filas=None, total=None):
    recibido = {}

    def _fn(conn, filtros, page, page_size, campo, direccion):
        recibido.update(
            filtros=filtros,
            page=page,
            page_size=page_size,
            campo=campo,
            direccion=direccion,
        )
        resultado = [_asiento()] if filas is None else filas
        return resultado, len(resultado) if total is None else total

    monkeypatch.setattr(repository, "listar_asientos", _fn)
    return recibido


def test_con04_contrato_en_openapi():
    spec = app.openapi()
    operacion = spec["paths"][_ASIENTOS]["get"]

    assert operacion["operationId"] == "CON04"
    assert operacion["x-roles"] == ["CONTADOR", "AUDITOR", "ADMIN"]
    parametros = {p["name"] for p in operacion["parameters"]}
    assert parametros == {
        "fecha",
        "origen",
        "idAgencia",
        "estado",
        "page",
        "pageSize",
        "sort",
    }
    esquema = operacion["responses"]["200"]["content"]["application/json"]["schema"]
    assert esquema["$ref"].endswith("/PageAsiento")
    pagina = spec["components"]["schemas"]["PageAsiento"]["properties"]
    assert set(pagina) == {"items", "page", "pageSize", "total"}
    asiento = spec["components"]["schemas"]["Asiento"]["properties"]
    assert set(asiento) == {*_ASIENTO_JSON, "detalle"}
    linea = spec["components"]["schemas"]["MovimientoAsiento"]["properties"]
    assert set(linea) == {
        "idMovimientoContable",
        "idCuentaContable",
        "codigoCuenta",
        "tipoMovimiento",
        "monto",
        "idTransaccion",
        "idAgencia",
    }


def test_con05_contrato_en_openapi():
    operacion = app.openapi()["paths"][f"{_ASIENTOS}/{{idAsiento}}"]["get"]

    assert operacion["operationId"] == "CON05"
    assert operacion["x-roles"] == ["CONTADOR", "AUDITOR", "ADMIN"]
    assert [p["name"] for p in operacion["parameters"]] == ["idAsiento"]
    esquema = operacion["responses"]["200"]["content"]["application/json"]["schema"]
    assert esquema["$ref"].endswith("/Asiento")
    assert "404" in operacion["responses"]


@pytest.mark.parametrize("rol", ["CONTADOR", "AUDITOR", "ADMIN"])
def test_con04_roles_permitidos_reciben_la_pagina(client, monkeypatch, rol):
    from tests.sesion import usuario_con_roles

    simular_sesion(app, usuario_con_roles(rol))
    _capturar_listado(monkeypatch, total=877)

    r = client.get(_ASIENTOS)

    assert r.status_code == 200
    assert r.json() == {
        "items": [{**_ASIENTO_JSON, "detalle": []}],
        "page": 1,
        "pageSize": 20,
        "total": 877,
    }


def test_con04_sin_parametros_usa_orden_y_pagina_por_defecto(client, monkeypatch):
    recibido = _capturar_listado(monkeypatch)

    r = client.get(_ASIENTOS)

    assert r.status_code == 200
    assert recibido == {
        "filtros": {"fecha": None, "origen": None, "id_agencia": None, "estado": None},
        "page": 1,
        "page_size": 20,
        "campo": "fechaAsiento",
        "direccion": "desc",
    }


def test_con04_filtros_normalizados_llegan_al_repositorio(client, monkeypatch):
    recibido = _capturar_listado(monkeypatch)

    r = client.get(
        _ASIENTOS,
        params={
            "fecha": "2026-11-04",
            "origen": " caja ",
            "idAgencia": "001",
            "estado": "contabilizado",
        },
    )

    assert r.status_code == 200
    assert recibido["filtros"] == {
        "fecha": date(2026, 11, 4),
        "origen": "CAJA",
        "id_agencia": "001",
        "estado": "CONTABILIZADO",
    }


def test_con04_origen_nuevo_no_es_rechazado(client, monkeypatch):
    # Texto libre, no enum: un origen que aún no existe en la DB se acepta.
    recibido = _capturar_listado(monkeypatch, filas=[])

    r = client.get(_ASIENTOS, params={"origen": "transferencia"})

    assert r.status_code == 200
    assert recibido["filtros"]["origen"] == "TRANSFERENCIA"
    assert r.json()["items"] == []
    assert r.json()["total"] == 0


def test_con04_paginacion_y_sort_llegan_al_repositorio(client, monkeypatch):
    recibido = _capturar_listado(monkeypatch, total=877)

    r = client.get(
        _ASIENTOS, params={"page": "3", "pageSize": "100", "sort": "totalDebito,asc"}
    )

    assert r.status_code == 200
    assert (recibido["page"], recibido["page_size"]) == (3, 100)
    assert (recibido["campo"], recibido["direccion"]) == ("totalDebito", "asc")
    assert (r.json()["page"], r.json()["pageSize"], r.json()["total"]) == (3, 100, 877)


@pytest.mark.parametrize(
    "sort",
    [
        "fechaAsiento",
        "fechaAsiento,DESC",
        "fechaAsiento,desc,extra",
        "concepto,asc",
        "FechaAsiento,asc",
        "fechaAsiento;DROP TABLE x,asc",
        ",asc",
    ],
)
def test_con04_sort_invalido_es_400(client, monkeypatch, sort):
    monkeypatch.setattr(repository, "listar_asientos", _NO_LLEGA)

    r = client.get(_ASIENTOS, params={"sort": sort})

    assert r.status_code == 400
    assert r.json()["code"] == "ORDEN_INVALIDO"
    assert sort not in r.json()["detail"]


@pytest.mark.parametrize(
    "fecha", ["2026-13-01", "2026-02-30", "04/11/2026", "20261104"]
)
def test_con04_fecha_invalida_es_400(client, monkeypatch, fecha):
    monkeypatch.setattr(repository, "listar_asientos", _NO_LLEGA)

    r = client.get(_ASIENTOS, params={"fecha": fecha})

    assert r.status_code == 400
    assert r.json()["code"] == "FECHA_INVALIDA"


@pytest.mark.parametrize(
    "consulta",
    [
        "page=0",
        "page=abc",
        "page=2147483648",
        "pageSize=0",
        "pageSize=101",
        "idAgencia=01",
        "idAgencia=0001",
        "origen=",
        f"origen={'X' * 21}",
        f"estado={'X' * 21}",
        f"sort={'x' * 41}",
    ],
)
def test_con04_parametros_invalidos_son_400(client, consulta):
    r = client.get(f"{_ASIENTOS}?{consulta}")

    assert r.status_code == 400
    assert r.json()["code"] == "DATOS_INVALIDOS"


def test_con04_filtro_solo_espacios_es_400(client, monkeypatch):
    monkeypatch.setattr(repository, "listar_asientos", _NO_LLEGA)

    r = client.get(_ASIENTOS, params={"estado": "   "})

    assert r.status_code == 400
    assert r.json()["code"] == "PARAMETRO_INVALIDO"


def test_con04_parametro_desconocido_o_repetido_es_400(client):
    desconocido = client.get(_ASIENTOS, params={"agencia": "001"})
    repetido = client.get(f"{_ASIENTOS}?estado=A&estado=B")

    for r in (desconocido, repetido):
        assert r.status_code == 400
        assert r.json()["code"] == "PARAMETRO_INVALIDO"


def test_con04_rol_fuera_de_la_tarea_recibe_403(client):
    from tests.sesion import usuario_con_roles

    simular_sesion(app, usuario_con_roles("ASESOR"))

    r = client.get(_ASIENTOS)

    assert r.status_code == 403
    assert r.json()["code"] == "SIN_PERMISO"


def test_con04_repositorio_arma_sql_parametrizado_y_paginado():
    conn = Mock(spec=Connection)
    conn.execute.return_value.scalar_one.return_value = 877
    conn.execute.return_value.mappings.return_value.all.return_value = []

    filas, total = repository.listar_asientos(
        conn,
        {"fecha": None, "origen": "CAJA", "id_agencia": "001", "estado": None},
        3,
        50,
        "numeroAsiento",
        "asc",
    )

    assert (filas, total) == ([], 877)
    (conteo, p_conteo), (consulta, p_consulta) = (
        (str(c.args[0]), c.args[1]) for c in conn.execute.call_args_list
    )
    assert "COUNT(*)" in conteo
    assert p_conteo == {"origen": "CAJA", "id_agencia": "001"}
    assert "Origen = :origen" in consulta
    assert "IdAgencia = :id_agencia" in consulta
    assert "FechaAsiento = :fecha" not in consulta
    assert "ORDER BY NumeroAsiento ASC, IdAsientoContable DESC" in consulta
    assert "OFFSET :offset ROWS FETCH NEXT :page_size ROWS ONLY" in consulta
    assert p_consulta == {
        "origen": "CAJA",
        "id_agencia": "001",
        "offset": 100,
        "page_size": 50,
    }


def test_con04_repositorio_sin_desempate_doble_al_ordenar_por_id():
    conn = Mock(spec=Connection)
    conn.execute.return_value.scalar_one.return_value = 0
    conn.execute.return_value.mappings.return_value.all.return_value = []

    repository.listar_asientos(
        conn,
        {
            "fecha": date(2026, 11, 4),
            "origen": None,
            "id_agencia": None,
            "estado": None,
        },
        1,
        20,
        "idAsientoContable",
        "desc",
    )

    consulta = str(conn.execute.call_args_list[1].args[0])
    assert "FechaAsiento = :fecha" in consulta
    assert "ORDER BY IdAsientoContable DESC OFFSET" in consulta


@pytest.mark.parametrize("rol", ["CONTADOR", "AUDITOR", "ADMIN"])
def test_con05_devuelve_asiento_con_detalle(client, monkeypatch, rol):
    from tests.sesion import usuario_con_roles

    simular_sesion(app, usuario_con_roles(rol))
    pedido = {}

    def _cabecera(conn, id_asiento):
        pedido["cabecera"] = id_asiento
        return _asiento()

    def _lineas(conn, id_asiento):
        pedido["lineas"] = id_asiento
        return [
            _movimiento(),
            _movimiento(
                id_movimiento_contable=11,
                id_cuenta_contable=8,
                codigo_cuenta="210135",
                tipo_movimiento="CREDITO",
                id_transaccion=None,
                id_agencia=None,
            ),
        ]

    monkeypatch.setattr(repository, "obtener_asiento", _cabecera)
    monkeypatch.setattr(repository, "movimientos_asiento", _lineas)

    r = client.get(f"{_ASIENTOS}/7")

    assert r.status_code == 200
    assert pedido == {"cabecera": 7, "lineas": 7}
    assert r.json() == {
        **_ASIENTO_JSON,
        "detalle": [
            {
                "idMovimientoContable": 10,
                "idCuentaContable": 3,
                "codigoCuenta": "110105",
                "tipoMovimiento": "DEBITO",
                "monto": 150.0,
                "idTransaccion": 9_000_000_001,
                "idAgencia": "001",
            },
            {
                "idMovimientoContable": 11,
                "idCuentaContable": 8,
                "codigoCuenta": "210135",
                "tipoMovimiento": "CREDITO",
                "monto": 150.0,
                "idTransaccion": None,
                "idAgencia": None,
            },
        ],
    }


def test_con05_asiento_reversado_publica_su_enlace(client, monkeypatch):
    monkeypatch.setattr(
        repository,
        "obtener_asiento",
        lambda conn, i: _asiento(estado="REVERSADO", id_asiento_reversion=8),
    )
    monkeypatch.setattr(repository, "movimientos_asiento", lambda conn, i: [])

    r = client.get(f"{_ASIENTOS}/7")

    assert r.status_code == 200
    assert r.json()["estado"] == "REVERSADO"
    assert r.json()["idAsientoReversion"] == 8


def test_con05_asiento_inexistente_es_404(client, monkeypatch):
    monkeypatch.setattr(repository, "obtener_asiento", lambda conn, i: None)
    monkeypatch.setattr(repository, "movimientos_asiento", _NO_LLEGA)

    r = client.get(f"{_ASIENTOS}/999999")

    assert r.status_code == 404
    assert r.json()["code"] == "ASIENTO_NO_ENCONTRADO"
    assert "999999" not in r.json()["detail"]


@pytest.mark.parametrize("id_asiento", ["0", "-1", "abc", "1.5", "2147483648"])
def test_con05_id_invalido_es_400(client, id_asiento):
    r = client.get(f"{_ASIENTOS}/{id_asiento}")

    assert r.status_code == 400
    assert r.json()["code"] == "DATOS_INVALIDOS"


def test_con05_parametros_de_consulta_son_400(client):
    r = client.get(f"{_ASIENTOS}/7", params={"detalle": "true"})

    assert r.status_code == 400
    assert r.json()["code"] == "PARAMETRO_INVALIDO"


def test_con05_rol_fuera_de_la_tarea_recibe_403(client):
    from tests.sesion import usuario_con_roles

    simular_sesion(app, usuario_con_roles("CAJERO"))

    r = client.get(f"{_ASIENTOS}/7")

    assert r.status_code == 403
    assert r.json()["code"] == "SIN_PERMISO"


def test_con05_repositorio_toma_codigo_de_cuenta_y_ordena_por_movimiento():
    conn = Mock(spec=Connection)
    conn.execute.return_value.mappings.return_value.all.return_value = []

    repository.movimientos_asiento(conn, 7)

    consulta = str(conn.execute.call_args.args[0])
    assert "JOIN Contabilidad.CuentasContables" in consulta
    assert "c.CodigoCuenta" in consulta
    assert "ORDER BY m.IdMovimientoContable" in consulta
    assert conn.execute.call_args.args[1] == {"id": 7}
