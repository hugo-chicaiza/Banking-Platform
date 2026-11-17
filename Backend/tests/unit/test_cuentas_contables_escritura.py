"""Contrato de #206: alta, edición, estado y baja de cuentas contables.

Los cambios sujetos a aprobación conservan su respuesta 501.
"""

import pytest
from fastapi.testclient import TestClient

from app.core.database.db import cooperativa
from app.main import app
from app.modules.contabilidad import repository
from tests.sesion import simular_sesion, usuario_con_roles

_BASE = "/api/v1/contabilidad/cuentas-contables"
_RUTA_ID = f"{_BASE}/{{idCuentaContable}}"
_RUTA_ESTADO = f"{_BASE}/{{idCuentaContable}}/estado"

_ALTA = {
    "codigoCuenta": "110105",
    "nombreCuenta": "Caja chica",
    "idCuentaSuperior": 12,
    "esImputable": True,
}

# (método, url concreta, cuerpo válido)
_OPERACIONES = [
    ("POST", _BASE, _ALTA),
    ("PATCH", f"{_BASE}/7", {"nombreCuenta": "Caja general"}),
    ("PATCH", f"{_BASE}/7/estado", {"estado": "Inactivo"}),
    ("DELETE", f"{_BASE}/7", None),
]


@pytest.fixture
def client():
    app.dependency_overrides[cooperativa] = lambda: None
    simular_sesion(app, usuario_con_roles("CONTADOR"))
    yield TestClient(app)
    app.dependency_overrides.clear()


def _llamar(client, metodo, url, cuerpo):
    return client.request(metodo, url, json=cuerpo)


# ---------------------------------------------------------------------------
# OpenAPI
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("ruta", "metodo", "operation_id", "estados"),
    [
        (_BASE, "post", "CON03Crear", {"201", "202", "400", "401", "403", "404"}),
        (_RUTA_ID, "patch", "CON03Editar", {"200", "400", "401", "403", "404"}),
        (_RUTA_ESTADO, "patch", "CON03Estado", {"200", "202", "404", "409"}),
        (_RUTA_ID, "delete", "CON03Eliminar", {"204", "202", "404", "409"}),
    ],
)
def test_contrato_en_openapi(ruta, metodo, operation_id, estados):
    operacion = app.openapi()["paths"][ruta][metodo]

    assert operacion["operationId"] == operation_id
    assert operacion["x-roles"] == ["CONTADOR"]
    assert estados <= set(operacion["responses"])
    assert ("501" in operacion["responses"]) == (operation_id != "CON03Editar")


def test_contrato_codigos_de_error_documentados():
    paths = app.openapi()["paths"]
    alta = paths[_BASE]["post"]["responses"]
    estado = paths[_RUTA_ESTADO]["patch"]["responses"]
    baja = paths[_RUTA_ID]["delete"]["responses"]

    assert "CODIGO_DUPLICADO" in alta["409"]["description"]
    assert "CUENTA_SUPERIOR_CON_MOVIMIENTOS" in alta["409"]["description"]
    assert "CODIGO_NO_CORRESPONDE_AL_PADRE" in alta["422"]["description"]
    assert "CUENTA_CON_SALDO" in estado["409"]["description"]
    assert "CUENTA_EN_USO" in baja["409"]["description"]
    # 202 sin cuerpo; 201 con el mismo esquema que CON-03
    assert "content" not in alta["202"]
    assert alta["201"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/CuentaContable"
    )
    assert "content" not in baja["204"]


@pytest.mark.parametrize(
    ("esquema", "campos", "requeridos"),
    [
        (
            "CuentaContableCrear",
            {"codigoCuenta", "nombreCuenta", "idCuentaSuperior", "esImputable"},
            {"codigoCuenta", "nombreCuenta", "idCuentaSuperior", "esImputable"},
        ),
        ("CuentaContableEditar", {"nombreCuenta"}, {"nombreCuenta"}),
        ("CuentaContableEstado", {"estado"}, {"estado"}),
    ],
)
def test_contrato_cuerpos_de_entrada(esquema, campos, requeridos):
    definicion = app.openapi()["components"]["schemas"][esquema]

    assert set(definicion["properties"]) == campos
    assert set(definicion["required"]) == requeridos
    assert definicion["additionalProperties"] is False


def test_contrato_estado_solo_acepta_activo_o_inactivo():
    estado = app.openapi()["components"]["schemas"]["CuentaContableEstado"]

    assert estado["properties"]["estado"]["enum"] == ["Activo", "Inactivo"]


# ---------------------------------------------------------------------------
# Sin lógica: 501
# ---------------------------------------------------------------------------


# Alta, edición y estado ya tienen lógica; la baja sigue solo con contrato.
@pytest.mark.parametrize(
    ("metodo", "url", "cuerpo"),
    [op for op in _OPERACIONES if op[0] == "DELETE"],
)
def test_contador_con_datos_validos_recibe_501(client, metodo, url, cuerpo):
    r = _llamar(client, metodo, url, cuerpo)

    assert r.status_code == 501
    assert r.json()["code"] == "OPERACION_NO_HABILITADA"
    assert r.headers["content-type"].startswith("application/problem+json")


# ---------------------------------------------------------------------------
# Roles: solo CONTADOR escribe; AUDITOR y ADMIN solo leen
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("rol", ["AUDITOR", "ADMIN", "CAJERO", "ASESOR"])
@pytest.mark.parametrize(("metodo", "url", "cuerpo"), _OPERACIONES)
def test_rol_distinto_de_contador_recibe_403(client, rol, metodo, url, cuerpo):
    simular_sesion(app, usuario_con_roles(rol))

    r = _llamar(client, metodo, url, cuerpo)

    assert r.status_code == 403
    assert r.json()["code"] == "SIN_PERMISO"


def test_auditor_sigue_leyendo_el_plan(client, monkeypatch):
    simular_sesion(app, usuario_con_roles("AUDITOR"))
    monkeypatch.setattr(repository, "listar_cuentas_contables", lambda c, q, i: [])

    assert client.get(_BASE).status_code == 200
    assert client.post(_BASE, json=_ALTA).status_code == 403


# ---------------------------------------------------------------------------
# Validación de entrada: 400
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "cambios",
    [
        {"idAgencia": "001"},  # campo desconocido (extra="forbid")
        {"idCuentaContable": 99},
        {"codigoCuenta": "11A105"},
        {"codigoCuenta": ""},
        {"codigoCuenta": "1" * 31},
        {"codigoCuenta": 110105},
        {"nombreCuenta": ""},
        {"nombreCuenta": "   "},
        {"nombreCuenta": "x" * 151},
        {"idCuentaSuperior": 0},
        {"idCuentaSuperior": "12"},
        {"idCuentaSuperior": 2_147_483_648},
        {"idCuentaSuperior": None},
        {"esImputable": "true"},
        {"esImputable": 1},
    ],
)
def test_alta_con_datos_invalidos_es_400(client, cambios):
    r = client.post(_BASE, json={**_ALTA, **cambios})

    assert r.status_code == 400
    assert r.json()["code"] == "DATOS_INVALIDOS"


@pytest.mark.parametrize(
    "faltante", ["codigoCuenta", "nombreCuenta", "idCuentaSuperior", "esImputable"]
)
def test_alta_sin_un_campo_requerido_es_400(client, faltante):
    cuerpo = {k: v for k, v in _ALTA.items() if k != faltante}

    r = client.post(_BASE, json=cuerpo)

    assert r.status_code == 400
    assert r.json()["code"] == "DATOS_INVALIDOS"


@pytest.mark.parametrize(
    "cuerpo",
    [
        {},
        {"nombreCuenta": ""},
        {"nombreCuenta": "Caja", "codigoCuenta": "1101"},  # el código no se edita
    ],
)
def test_edicion_con_datos_invalidos_es_400(client, cuerpo):
    r = client.patch(f"{_BASE}/7", json=cuerpo)

    assert r.status_code == 400
    assert r.json()["code"] == "DATOS_INVALIDOS"


@pytest.mark.parametrize(
    "cuerpo",
    [
        {},
        {"estado": "ACTIVO"},
        {"estado": "inactivo"},
        {"estado": True},
        {"estado": "Inactivo", "motivo": "x"},
    ],
)
def test_estado_invalido_es_400(client, cuerpo):
    r = client.patch(f"{_BASE}/7/estado", json=cuerpo)

    assert r.status_code == 400
    assert r.json()["code"] == "DATOS_INVALIDOS"


@pytest.mark.parametrize("id_cuenta", ["0", "-1", "abc", "1.5", "2147483648"])
@pytest.mark.parametrize(
    ("metodo", "sufijo", "cuerpo"),
    [
        ("PATCH", "", {"nombreCuenta": "Caja"}),
        ("PATCH", "/estado", {"estado": "Activo"}),
        ("DELETE", "", None),
    ],
)
def test_id_de_cuenta_invalido_es_400(client, id_cuenta, metodo, sufijo, cuerpo):
    r = _llamar(client, metodo, f"{_BASE}/{id_cuenta}{sufijo}", cuerpo)

    assert r.status_code == 400
    assert r.json()["code"] == "DATOS_INVALIDOS"


@pytest.mark.parametrize(("metodo", "url", "cuerpo"), _OPERACIONES)
def test_parametros_de_consulta_son_400(client, metodo, url, cuerpo):
    r = _llamar(client, metodo, f"{url}?forzar=true", cuerpo)

    assert r.status_code == 400
    assert r.json()["code"] == "PARAMETRO_INVALIDO"


def test_json_mal_formado_es_400(client):
    r = client.post(
        _BASE, content=b"{no es json", headers={"Content-Type": "application/json"}
    )

    assert r.status_code == 400
    assert r.json()["code"] == "DATOS_INVALIDOS"
