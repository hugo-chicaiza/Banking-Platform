from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.core.db import cooperativa
from app.main import app
from app.modules.catalogos import repository
from app.modules.catalogos.router import router


@pytest.fixture
def client():
    # Sin BD: cada prueba reemplaza la función del repositorio
    app.dependency_overrides[cooperativa] = lambda: None
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


PRODUCTOS = {
    "Cuenta": {
        "id_producto": 1,
        "codigo_producto": "AHO-01",
        "nombre_producto": "Ahorro a la vista",
        "tipo_producto": "Cuenta",
        "monto_apertura_minimo": Decimal("10.00"),
        "id_tipo_credito": None,
        "id_red": None,
        "tipo_cuenta": "Ahorro",
        "permite_operaciones_presenciales": True,
    },
    "Tarjeta": {
        "id_producto": 2,
        "codigo_producto": "TAR-01",
        "nombre_producto": "Tarjeta débito",
        "tipo_producto": "Tarjeta",
        "monto_apertura_minimo": None,
        "id_tipo_credito": None,
        "id_red": 3,
        "tipo_cuenta": None,
        "permite_operaciones_presenciales": True,
    },
    "Credito": {
        "id_producto": 3,
        "codigo_producto": "CRE-01",
        "nombre_producto": "Crédito personal",
        "tipo_producto": "Credito",
        "monto_apertura_minimo": None,
        "id_tipo_credito": 4,
        "id_red": None,
        "tipo_cuenta": None,
        "permite_operaciones_presenciales": False,
    },
}


def test_productos_sin_filtro(client, monkeypatch):
    productos = list(PRODUCTOS.values())
    llamadas = []

    def listar(conn, tipo):
        llamadas.append(tipo)
        return productos

    monkeypatch.setattr(repository, "listar_productos", listar)

    r = client.get("/api/v1/catalogos/productos")

    assert r.status_code == 200
    assert llamadas == [None]
    assert r.json() == [
        {
            "idProducto": 1,
            "codigoProducto": "AHO-01",
            "nombreProducto": "Ahorro a la vista",
            "tipoProducto": "Cuenta",
            "montoAperturaMinimo": 10.0,
            "idTipoCredito": None,
            "idRed": None,
            "tipoCuenta": "Ahorro",
            "permiteOperacionesPresenciales": True,
        },
        {
            "idProducto": 2,
            "codigoProducto": "TAR-01",
            "nombreProducto": "Tarjeta débito",
            "tipoProducto": "Tarjeta",
            "montoAperturaMinimo": None,
            "idTipoCredito": None,
            "idRed": 3,
            "tipoCuenta": None,
            "permiteOperacionesPresenciales": True,
        },
        {
            "idProducto": 3,
            "codigoProducto": "CRE-01",
            "nombreProducto": "Crédito personal",
            "tipoProducto": "Credito",
            "montoAperturaMinimo": None,
            "idTipoCredito": 4,
            "idRed": None,
            "tipoCuenta": None,
            "permiteOperacionesPresenciales": False,
        },
    ]


@pytest.mark.parametrize("tipo", ["Cuenta", "Tarjeta", "Credito"])
def test_productos_filtrados_por_tipo(client, monkeypatch, tipo):
    llamadas = []
    producto = PRODUCTOS[tipo]

    def listar(conn, filtro):
        llamadas.append(filtro)
        return [producto]

    monkeypatch.setattr(repository, "listar_productos", listar)

    r = client.get("/api/v1/catalogos/productos", params={"tipo": tipo})

    assert r.status_code == 200
    assert llamadas == [tipo]
    assert r.json()[0]["tipoProducto"] == tipo


def test_productos_tipo_invalido_devuelve_problem_details(client, monkeypatch):
    monkeypatch.setattr(
        repository,
        "listar_productos",
        lambda *_: pytest.fail("No debe consultar el repositorio"),
    )

    r = client.get("/api/v1/catalogos/productos", params={"tipo": "Otro"})

    assert r.status_code == 400
    assert r.headers["content-type"] == "application/problem+json"
    assert r.headers["x-request-id"] == r.json()["traceId"]
    assert r.json()["type"] == "about:blank"
    assert r.json()["title"] == "Bad Request"
    assert r.json()["status"] == 400
    assert r.json()["code"] == "VALIDATION_ERROR"
    assert r.json()["errors"] == [
        {
            "field": "tipo",
            "message": "Debe ser uno de: Cuenta, Tarjeta, Credito.",
        }
    ]


def test_productos_openapi_generado_expone_enum_y_problem_details():
    operation = app.openapi()["paths"]["/api/v1/catalogos/productos"]["get"]
    tipo = next(param for param in operation["parameters"] if param["name"] == "tipo")

    assert tipo["schema"]["enum"] == ["Cuenta", "Tarjeta", "Credito"]
    problem_content = operation["responses"]["400"]["content"]
    assert list(problem_content) == ["application/problem+json"]
    assert "traceId" in problem_content["application/problem+json"]["schema"][
        "properties"
    ]
    assert all(
        list(operation["responses"][status]["content"])
        == ["application/problem+json"]
        for status in ("400", "401", "403")
    )
    assert operation["responses"]["200"]["content"]["application/json"]["schema"][
        "type"
    ] == "array"
    product_schema = app.openapi()["components"]["schemas"]["Producto"]
    assert set(product_schema["properties"]) == {
        "idProducto",
        "codigoProducto",
        "nombreProducto",
        "tipoProducto",
        "montoAperturaMinimo",
        "idTipoCredito",
        "idRed",
        "tipoCuenta",
        "permiteOperacionesPresenciales",
    }


def test_productos_router_usa_autenticacion_central():
    route = next(route for route in router.routes if route.path == "/catalogos/productos")

    assert any(
        dependency.call.__name__ == "require_auth"
        for dependency in route.dependant.dependencies
    )


@pytest.mark.skip(
    reason="F-03 pendiente: require_auth todavía no valida JWT ni rechaza solicitudes sin token."
)
def test_productos_sin_token_401(client, monkeypatch):
    monkeypatch.setattr(repository, "listar_productos", lambda *_: [])

    r = client.get("/api/v1/catalogos/productos")

    assert r.status_code == 401


class _EmptyResult:
    def mappings(self):
        return []


class _FakeConnection:
    def execute(self, statement, parameters):
        self.sql = str(statement)
        self.parameters = parameters
        return _EmptyResult()


def test_repository_productos_consulta_tablas_y_filtra_de_forma_parametrizada():
    conn = _FakeConnection()

    assert repository.listar_productos(conn, "Tarjeta") == []

    assert "ProductosFinancieros.Producto AS p" in conn.sql
    assert "ProductosFinancieros.Red AS r" in conn.sql
    assert "p.Estado = 'A'" in conn.sql
    assert "p.TipoProducto = :tipo" in conn.sql
    assert "ORDER BY p.TipoProducto, p.NombreProducto" in conn.sql
    assert conn.parameters == {"tipo": "Tarjeta"}
