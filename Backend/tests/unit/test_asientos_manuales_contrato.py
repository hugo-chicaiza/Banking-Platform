"""Contrato de E4-04 (#383): asientos manuales con aprobación y reverso.

Solo contrato: como las demás ramas pendientes de E0-09, cada ruta responde 404
FUNCION_NO_DISPONIBLE con datos válidos (funcion_pendiente). La bandera se simula y la
conexión es un Mock que no debe usarse (no hay lógica que llegue a la BD).
"""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.core.api.errors import problema
from app.core.database.db import cooperativa
from app.core.security.auth import ROLES
from app.main import app
from app.modules.contabilidad import schemas
from app.modules.parametros import funciones
from tests.sesion import simular_sesion, usuario_con_roles

_BASE = "/api/v1/contabilidad/asientos"
_RUTA_ID = f"{_BASE}/{{idAsiento}}"

_BORRADOR = {
    "concepto": "Provisión de vacaciones de noviembre",
    "idAgencia": "001",
    "lineas": [
        {"idCuentaContable": 931, "tipoMovimiento": "DEBITO", "monto": 150.25},
        {"idCuentaContable": 1213, "tipoMovimiento": "CREDITO", "monto": "150.25"},
    ],
}
_MOTIVO = {"motivo": "Se registró en la cuenta equivocada"}

# (método, url concreta, cuerpo válido)
_OPERACIONES = [
    ("POST", _BASE, _BORRADOR),
    ("PUT", f"{_BASE}/7", _BORRADOR),
    ("POST", f"{_BASE}/7/envio", None),
    ("POST", f"{_BASE}/7/anulacion", _MOTIVO),
    ("POST", f"{_BASE}/7/reverso", _MOTIVO),
]
_MANUAL = "FUNCION_CONTABILIDAD_ASIENTO_MANUAL"
_REVERSO = "FUNCION_CONTABILIDAD_REVERSO_ASIENTO"
_CLAVES = {
    url: _REVERSO if url.endswith("/reverso") else _MANUAL for _, url, _ in _OPERACIONES
}
_CON_CUERPO_DE_ASIENTO = [op for op in _OPERACIONES if op[2] is _BORRADOR]
_CON_MOTIVO = [op for op in _OPERACIONES if op[2] is _MOTIVO]


@pytest.fixture
def conn():
    return MagicMock()


@pytest.fixture(autouse=True)
def banderas(monkeypatch):
    """Bandera E0-09 apagada (las claves no tienen semilla); registra la consultada."""
    estado = {"consultadas": [], "activa": False}

    def requiere_funcion(clave):
        def verificar(conn, usuario):
            estado["consultadas"].append(clave)
            if not estado["activa"]:
                raise problema(404, "FUNCION_NO_DISPONIBLE", "Apagada")

        return verificar

    monkeypatch.setattr(funciones, "requiere_funcion", requiere_funcion)
    return estado


@pytest.fixture
def client(conn):
    app.dependency_overrides[cooperativa] = lambda: conn
    simular_sesion(app, usuario_con_roles("CONTADOR"))
    yield TestClient(app)
    app.dependency_overrides.clear()


def _llamar(client, metodo, url, cuerpo):
    return client.request(metodo, url, json=cuerpo)


def _campos(respuesta):
    return {e["field"] for e in respuesta.json().get("errors", [])}


# ---------------------------------------------------------------------------
# OpenAPI
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("ruta", "metodo", "operation_id", "exito"),
    [
        (_BASE, "post", "E404Crear", "201"),
        (_RUTA_ID, "put", "E404Editar", "200"),
        (f"{_RUTA_ID}/envio", "post", "E404Envio", "202"),
        (f"{_RUTA_ID}/anulacion", "post", "E404Anulacion", "200"),
        (f"{_RUTA_ID}/reverso", "post", "CON06Reverso", "202"),
    ],
)
def test_contrato_en_openapi(ruta, metodo, operation_id, exito):
    operacion = app.openapi()["paths"][ruta][metodo]

    assert operacion["operationId"] == operation_id
    assert operacion["x-roles"] == ["CONTADOR"]
    assert {exito, "400", "401", "403", "404"} <= set(operacion["responses"])
    assert "FUNCION_NO_DISPONIBLE" in operacion["responses"]["404"]["description"]
    assert "501" not in operacion["responses"]
    problema = operacion["responses"]["400"]["content"]
    assert "application/problem+json" in problema


def test_cada_ruta_tiene_un_solo_operation_id():
    ids = [
        op["operationId"]
        for camino, metodos in app.openapi()["paths"].items()
        if camino.startswith(_BASE)
        for op in metodos.values()
    ]
    assert len(ids) == len(set(ids))


def test_respuestas_exitosas():
    paths = app.openapi()["paths"]

    def esquema(ruta, metodo, estado):
        return paths[ruta][metodo]["responses"][estado]["content"]["application/json"][
            "schema"
        ]["$ref"].rsplit("/", 1)[-1]

    assert esquema(_BASE, "post", "201") == "AsientoManualCreado"
    assert esquema(_RUTA_ID, "put", "200") == "Asiento"
    assert esquema(f"{_RUTA_ID}/anulacion", "post", "200") == "Asiento"
    assert esquema(f"{_RUTA_ID}/envio", "post", "202") == "SolicitudAceptada"
    assert esquema(f"{_RUTA_ID}/reverso", "post", "202") == "SolicitudAceptada"
    creado = app.openapi()["components"]["schemas"]["AsientoManualCreado"]
    assert set(creado["properties"]) == {"idAsientoContable"}


def test_envio_no_lleva_cuerpo():
    assert "requestBody" not in app.openapi()["paths"][f"{_RUTA_ID}/envio"]["post"]


@pytest.mark.parametrize(
    ("ruta", "metodo", "estado", "codigos"),
    [
        (_RUTA_ID, "put", "409", {"ASIENTO_NO_EDITABLE"}),
        (_RUTA_ID, "put", "404", {"ASIENTO_NO_ENCONTRADO", "FUNCION_NO_DISPONIBLE"}),
        (
            f"{_RUTA_ID}/reverso",
            "post",
            "404",
            {"ASIENTO_NO_ENCONTRADO", "FUNCION_NO_DISPONIBLE"},
        ),
        (
            f"{_RUTA_ID}/envio",
            "post",
            "422",
            {"ASIENTO_NO_CUADRA", "CUENTA_SOLO_AUTOMATICA"},
        ),
        (
            f"{_RUTA_ID}/envio",
            "post",
            "409",
            {
                "ASIENTO_NO_EDITABLE",
                "CUENTA_CONTABLE_NO_HABILITADA",
                "PERIODO_CONTABLE_NO_ABIERTO",
            },
        ),
        (
            f"{_RUTA_ID}/envio",
            "post",
            "403",
            {"SIN_PERMISO", "APROBADOR_ES_SOLICITANTE"},
        ),
        (f"{_RUTA_ID}/anulacion", "post", "409", {"ASIENTO_NO_EDITABLE"}),
        (
            f"{_RUTA_ID}/reverso",
            "post",
            "409",
            {
                "ASIENTO_DE_OPERACION",
                "ASIENTO_YA_REVERSADO",
                "ASIENTO_NO_REVERSABLE",
                "CUENTA_CONTABLE_NO_HABILITADA",
            },
        ),
        (
            f"{_RUTA_ID}/reverso",
            "post",
            "403",
            {"SIN_PERMISO", "APROBADOR_ES_SOLICITANTE"},
        ),
    ],
)
def test_codigos_de_error_documentados(ruta, metodo, estado, codigos):
    descripcion = app.openapi()["paths"][ruta][metodo]["responses"][estado][
        "description"
    ]

    for codigo in codigos:
        assert codigo in descripcion


def test_esquema_del_borrador():
    componentes = app.openapi()["components"]["schemas"]
    asiento = componentes["AsientoManual"]
    linea = componentes["LineaAsientoManual"]
    motivo = componentes["MotivoAsientoManual"]

    assert set(asiento["required"]) == {"concepto", "idAgencia", "lineas"}
    assert asiento["additionalProperties"] is False
    assert asiento["properties"]["concepto"]["maxLength"] == 200
    assert asiento["properties"]["idAgencia"]["pattern"] == "^[0-9]{3}$"
    assert "minItems" not in asiento["properties"]["lineas"]  # borrador incompleto
    assert asiento["properties"]["lineas"]["maxItems"] == schemas.MAX_LINEAS_ASIENTO
    assert set(linea["required"]) == {"idCuentaContable", "tipoMovimiento", "monto"}
    assert linea["additionalProperties"] is False
    assert linea["properties"]["tipoMovimiento"]["enum"] == ["DEBITO", "CREDITO"]
    assert {"type": "number", "exclusiveMinimum": 0} in linea["properties"]["monto"][
        "anyOf"
    ]
    assert motivo["properties"]["motivo"]["maxLength"] == 300
    assert motivo["additionalProperties"] is False


def test_con03_publica_solo_automatica():
    cuenta = app.openapi()["components"]["schemas"]["CuentaContable"]

    assert cuenta["properties"]["soloAutomatica"]["type"] == "boolean"
    assert "soloAutomatica" in cuenta["required"]


# ---------------------------------------------------------------------------
# Rama pendiente (E0-09): 404 FUNCION_NO_DISPONIBLE, sin tocar la BD
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("metodo", "url", "cuerpo"), _OPERACIONES)
def test_contador_con_datos_validos_recibe_404(
    client, conn, banderas, metodo, url, cuerpo
):
    r = _llamar(client, metodo, url, cuerpo)

    assert r.status_code == 404
    assert r.json()["code"] == "FUNCION_NO_DISPONIBLE"
    assert r.headers["content-type"].startswith("application/problem+json")
    assert banderas["consultadas"] == [_CLAVES[url]]
    assert conn.mock_calls == []


@pytest.mark.parametrize(("metodo", "url", "cuerpo"), _OPERACIONES)
def test_rama_pendiente_sigue_cerrada_con_la_bandera_activa(
    client, conn, banderas, metodo, url, cuerpo
):
    # Como en E0-09: una bandera activa no sustituye la implementación pendiente.
    banderas["activa"] = True

    r = _llamar(client, metodo, url, cuerpo)

    assert r.status_code == 404
    assert r.json()["code"] == "FUNCION_NO_DISPONIBLE"
    assert conn.mock_calls == []


@pytest.mark.parametrize(
    "lineas",
    [
        [],  # sin líneas
        [_BORRADOR["lineas"][0]],  # una sola línea
        [  # no cuadra
            {"idCuentaContable": 931, "tipoMovimiento": "DEBITO", "monto": 10},
            {"idCuentaContable": 1213, "tipoMovimiento": "CREDITO", "monto": 9},
        ],
    ],
    ids=["sin-lineas", "una-linea", "no-cuadra"],
)
@pytest.mark.parametrize(("metodo", "url", "cuerpo"), _CON_CUERPO_DE_ASIENTO)
def test_borrador_incompleto_no_es_error_de_datos(client, metodo, url, cuerpo, lineas):
    # El cuadre y el mínimo de dos líneas son del envío, no del borrador.
    r = _llamar(client, metodo, url, {**cuerpo, "lineas": lineas})

    assert r.status_code == 404
    assert r.json()["code"] == "FUNCION_NO_DISPONIBLE"


# ---------------------------------------------------------------------------
# Roles: solo CONTADOR
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("rol", [r for r in ROLES if r != "CONTADOR"])
@pytest.mark.parametrize(("metodo", "url", "cuerpo"), _OPERACIONES)
def test_otro_rol_recibe_403(client, conn, banderas, rol, metodo, url, cuerpo):
    simular_sesion(app, usuario_con_roles(rol))

    r = _llamar(client, metodo, url, cuerpo)

    assert r.status_code == 403
    assert r.json()["code"] == "SIN_PERMISO"
    assert conn.mock_calls == []
    assert banderas["consultadas"] == []  # el rol se valida antes que la bandera


# ---------------------------------------------------------------------------
# 400 ProblemDetails
# ---------------------------------------------------------------------------


def _linea(**cambios):
    return {**_BORRADOR["lineas"][0], **cambios}


@pytest.mark.parametrize(
    ("cambio", "campo"),
    [
        ({"extra": 1}, "extra"),
        ({"concepto": ""}, "concepto"),
        ({"concepto": "   "}, "concepto"),
        ({"concepto": "x" * 201}, "concepto"),
        ({"idAgencia": "1"}, "idAgencia"),
        ({"idAgencia": "00A"}, "idAgencia"),
        ({"lineas": [_linea(monto=0)]}, "lineas.0.monto"),
        ({"lineas": [_linea(monto=-5)]}, "lineas.0.monto"),
        ({"lineas": [_linea(monto="10.555")]}, "lineas.0.monto"),
        ({"lineas": [_linea(monto="10000000000000000.00")]}, "lineas.0.monto"),
        (
            {"lineas": [_linea(), _linea(tipoMovimiento="HABER")]},
            "lineas.1.tipoMovimiento",
        ),
        ({"lineas": [_linea(idCuentaContable="931")]}, "lineas.0.idCuentaContable"),
        ({"lineas": [_linea(idCuentaContable=0)]}, "lineas.0.idCuentaContable"),
        ({"lineas": [_linea(saldo=1)]}, "lineas.0.saldo"),
        (
            {"lineas": [_linea()] * (schemas.MAX_LINEAS_ASIENTO + 1)},
            "lineas",
        ),
    ],
    ids=lambda v: str(v)[:40],
)
@pytest.mark.parametrize(("metodo", "url", "cuerpo"), _CON_CUERPO_DE_ASIENTO)
def test_borrador_invalido_es_400(client, banderas, metodo, url, cuerpo, cambio, campo):
    r = _llamar(client, metodo, url, {**cuerpo, **cambio})

    assert r.status_code == 400
    assert r.json()["code"] == "DATOS_INVALIDOS"
    assert r.headers["content-type"].startswith("application/problem+json")
    assert campo in _campos(r)
    assert banderas["consultadas"] == []


@pytest.mark.parametrize(("metodo", "url", "cuerpo"), _CON_CUERPO_DE_ASIENTO)
@pytest.mark.parametrize("faltante", ["concepto", "idAgencia", "lineas"])
def test_borrador_sin_campo_obligatorio_es_400(client, metodo, url, cuerpo, faltante):
    r = _llamar(client, metodo, url, {k: v for k, v in cuerpo.items() if k != faltante})

    assert r.status_code == 400
    assert faltante in _campos(r)


@pytest.mark.parametrize(
    ("cuerpo", "campo"),
    [
        ({}, "motivo"),
        ({"motivo": ""}, "motivo"),
        ({"motivo": "  "}, "motivo"),
        ({"motivo": "x" * 301}, "motivo"),
        ({**_MOTIVO, "extra": True}, "extra"),
    ],
    ids=["sin-motivo", "vacio", "espacios", "301", "extra"],
)
@pytest.mark.parametrize(("metodo", "url", "_"), _CON_MOTIVO)
def test_motivo_invalido_es_400(client, metodo, url, _, cuerpo, campo):
    r = _llamar(client, metodo, url, cuerpo)

    assert r.status_code == 400
    assert r.json()["code"] == "DATOS_INVALIDOS"
    assert campo in _campos(r)


@pytest.mark.parametrize(("metodo", "url", "_"), _CON_MOTIVO)
def test_motivo_de_300_es_valido(client, metodo, url, _):
    assert _llamar(client, metodo, url, {"motivo": "x" * 300}).status_code == 404


@pytest.mark.parametrize(("metodo", "url", "cuerpo"), _OPERACIONES)
def test_parametro_de_consulta_desconocido_es_400(client, metodo, url, cuerpo):
    r = client.request(metodo, url, json=cuerpo, params={"estado": "BORRADOR"})

    assert r.status_code == 400
    assert r.json()["code"] == "PARAMETRO_INVALIDO"


@pytest.mark.parametrize("id_asiento", ["0", "-1", "2147483648", "abc"])
@pytest.mark.parametrize(
    ("metodo", "sufijo", "cuerpo"),
    [
        ("PUT", "", _BORRADOR),
        ("POST", "/envio", None),
        ("POST", "/anulacion", _MOTIVO),
        ("POST", "/reverso", _MOTIVO),
    ],
)
def test_id_de_asiento_invalido_es_400(client, metodo, sufijo, cuerpo, id_asiento):
    r = _llamar(client, metodo, f"{_BASE}/{id_asiento}{sufijo}", cuerpo)

    assert r.status_code == 400
    assert r.json()["code"] == "DATOS_INVALIDOS"


def test_con03_lee_solo_automatica_de_la_bd():
    from unittest.mock import Mock

    from app.modules.contabilidad import repository

    conn = Mock()
    conn.execute.return_value.mappings.return_value.all.return_value = []
    repository.listar_cuentas_contables(conn, None, None)
    listado = str(conn.execute.call_args.args[0])

    # El listado (CON-03) y la lectura de una cuenta (#206) publican el mismo esquema
    assert "SoloAutomatica   AS solo_automatica" in listado
    assert "SoloAutomatica    AS solo_automatica" in repository._CUENTA
