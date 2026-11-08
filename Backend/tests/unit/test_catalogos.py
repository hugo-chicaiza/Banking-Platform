from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.core.database.db import cooperativa
from app.main import app
from app.modules.catalogos import repository
from tests.sesion import simular_sesion


@pytest.fixture
def client():
    # Sin BD: cada prueba reemplaza la función del repositorio
    app.dependency_overrides[cooperativa] = lambda: None
    simular_sesion(app)
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_paises_con_datos(client, monkeypatch):
    rows = [{"codigo_pais": "ECU", "codigo_numerico": "218", "nombre_pais": "Ecuador"}]
    monkeypatch.setattr(repository, "listar_paises", lambda conn: rows)

    r = client.get("/api/v1/catalogos/paises")

    assert r.status_code == 200
    assert r.json() == [
        {"codigoPais": "ECU", "codigoNumerico": "218", "nombrePais": "Ecuador"}
    ]


def test_paises_sin_datos(client, monkeypatch):
    monkeypatch.setattr(repository, "listar_paises", lambda conn: [])

    r = client.get("/api/v1/catalogos/paises")

    assert r.status_code == 200
    assert r.json() == []


def test_denominaciones_valor_es_numero(client, monkeypatch):
    rows = [
        {
            "id_denominacion": 4,
            "tipo_pieza": "Billete",
            "valor": Decimal("20.00"),
            "descripcion": "Billete de 20",
        },
        {
            "id_denominacion": 8,
            "tipo_pieza": "Moneda",
            "valor": Decimal("0.25"),
            "descripcion": "Moneda de 25",
        },
    ]
    monkeypatch.setattr(repository, "listar_denominaciones", lambda conn: rows)

    r = client.get("/api/v1/catalogos/denominaciones")

    assert r.status_code == 200
    assert r.json() == [
        {
            "idDenominacion": 4,
            "tipoPieza": "Billete",
            "valor": 20.0,
            "descripcion": "Billete de 20",
        },
        {
            "idDenominacion": 8,
            "tipoPieza": "Moneda",
            "valor": 0.25,
            "descripcion": "Moneda de 25",
        },
    ]


def test_tipos_movimiento_caja_con_datos(client, monkeypatch):
    rows = [
        {
            "id_tipo_movimiento_caja": 1,
            "codigo": "DEPOSITO",
            "descripcion": "Depósito",
            "naturaleza": "I",
        }
    ]
    monkeypatch.setattr(repository, "listar_tipos_movimiento_caja", lambda conn: rows)

    r = client.get("/api/v1/catalogos/tipos-movimiento-caja")

    assert r.status_code == 200
    assert r.json() == [
        {
            "idTipoMovimientoCaja": 1,
            "codigo": "DEPOSITO",
            "descripcion": "Depósito",
            "naturaleza": "I",
        }
    ]


def test_actividades_economicas_con_datos(client, monkeypatch):
    rows = [
        {
            "id_actividad_economica": 4,
            "descripcion": "Comercio al por menor",
            "area_actividad": "Comercio",
        }
    ]
    monkeypatch.setattr(repository, "listar_actividades_economicas", lambda conn: rows)

    r = client.get("/api/v1/catalogos/actividades-economicas")

    assert r.status_code == 200
    assert r.json() == [
        {
            "idActividadEconomica": 4,
            "descripcion": "Comercio al por menor",
            "areaActividad": "Comercio",
        }
    ]


def test_tipos_antecedente_con_datos(client, monkeypatch):
    rows = [
        {
            "id_tipo_antecedente": 2,
            "nombre": "Lista OFAC",
            "categoria": "Critico",
            "puede_impedir_vinculacion": True,
        }
    ]
    monkeypatch.setattr(repository, "listar_tipos_antecedente", lambda conn: rows)

    r = client.get("/api/v1/catalogos/tipos-antecedente")

    assert r.status_code == 200
    assert r.json() == [
        {
            "idTipoAntecedente": 2,
            "nombre": "Lista OFAC",
            "categoria": "Critico",
            "puedeImpedirVinculacion": True,
        }
    ]


_PRODUCTO_CUENTA = {
    "id_producto": 1,
    "codigo_producto": "AHO001",
    "nombre_producto": "Ahorro a la vista",
    "tipo_producto": "Cuenta",
    "monto_apertura_minimo": Decimal("20.00"),
    "id_tipo_credito": None,
    "id_red": None,
    "tipo_cuenta": "Ahorro",
    "permite_operaciones_presenciales": True,
    "subproductos": [
        {
            "id_sub_producto": 1,
            "codigo_sub_producto": "AHO001-PN",
            "nombre_sub_producto": "Ahorro a la vista persona natural",
        }
    ],
}


def test_productos_sin_filtro_devuelve_nulos_y_monto_numerico(client, monkeypatch):
    llamada = {}

    def listar(_conn, tipo):
        llamada["tipo"] = tipo
        return [_PRODUCTO_CUENTA]

    monkeypatch.setattr(repository, "listar_productos", listar)

    r = client.get("/api/v1/catalogos/productos")

    assert r.status_code == 200
    assert llamada["tipo"] is None
    assert r.json() == [
        {
            "idProducto": 1,
            "codigoProducto": "AHO001",
            "nombreProducto": "Ahorro a la vista",
            "tipoProducto": "Cuenta",
            "montoAperturaMinimo": 20.0,
            "idTipoCredito": None,
            "idRed": None,
            "tipoCuenta": "Ahorro",
            "permiteOperacionesPresenciales": True,
            "subproductos": [
                {
                    "idSubProducto": 1,
                    "codigoSubProducto": "AHO001-PN",
                    "nombreSubProducto": "Ahorro a la vista persona natural",
                }
            ],
        }
    ]


@pytest.mark.parametrize("tipo", ["Cuenta", "Tarjeta", "Credito"])
def test_productos_filtra_por_cada_tipo(client, monkeypatch, tipo):
    llamada = {}

    def listar(_conn, recibido):
        llamada["tipo"] = recibido
        return []

    monkeypatch.setattr(repository, "listar_productos", listar)

    r = client.get("/api/v1/catalogos/productos", params={"tipo": tipo})

    assert r.status_code == 200
    assert llamada["tipo"] == tipo


@pytest.mark.parametrize("tipo", ["Otro", "cuenta", "' OR 1=1 --"])
def test_productos_tipo_invalido_400(client, tipo):
    r = client.get("/api/v1/catalogos/productos", params={"tipo": tipo})

    assert r.status_code == 400
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["code"] == "DATOS_INVALIDOS"
    assert r.json()["errors"][0]["field"] == "tipo"
    assert tipo not in r.text


@pytest.mark.parametrize("query", ["tipo=Cuenta&tipo=Credito", "otro=1"])
def test_productos_parametros_ambiguos_400(client, query):
    r = client.get(f"/api/v1/catalogos/productos?{query}")

    assert r.status_code == 400
    assert r.json()["code"] == "PARAMETRO_INVALIDO"


def test_canales_con_datos(client, monkeypatch):
    rows = [
        {
            "id_canal": 2,
            "codigo_canal": "ATM",
            "nombre_canal": "Cajero automático",
            "requiere_tarjeta": True,
            "requiere_pin": True,
            "requiere_terminal": True,
            "requiere_jornada_caja": False,
            "modo": "Presencial",
        }
    ]

    monkeypatch.setattr(
        repository,
        "listar_canales",
        lambda conn: rows,
    )

    r = client.get("/api/v1/catalogos/canales")

    assert r.status_code == 200
    assert r.json() == [
        {
            "idCanal": 2,
            "codigoCanal": "ATM",
            "nombreCanal": "Cajero automático",
            "requiereTarjeta": True,
            "requierePin": True,
            "requiereTerminal": True,
            "requiereJornadaCaja": False,
            "modo": "Presencial",
        }
    ]


def test_canales_sin_datos(client, monkeypatch):
    monkeypatch.setattr(
        repository,
        "listar_canales",
        lambda conn: [],
    )

    r = client.get("/api/v1/catalogos/canales")

    assert r.status_code == 200
    assert r.json() == []


def test_agencias_sql_ordena_matriz_primero():
    # CAT-06: el orden no depende del código; una sucursal "AMB-..." no pasa a la Matriz
    capturado: dict[str, str] = {}

    class _Conn:
        def execute(self, sql, params):
            capturado["sql"] = " ".join(str(sql).split())

            class _R:
                def mappings(self):
                    return []

            return _R()

    repository.listar_agencias(_Conn())  # type: ignore[arg-type]

    assert (
        "ORDER BY CASE a.TipoAgencia WHEN 'Matriz' THEN 0 ELSE 1 END, a.Codigo"
        in capturado["sql"]
    )
