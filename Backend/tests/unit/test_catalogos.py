from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.core.db import cooperativa
from app.main import app
from app.modules.catalogos import repository


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


# TODO(F-03): agregar test_sin_token_401 cuando require_auth valide el JWT


def test_tipos_antecedente_con_datos(client, monkeypatch):
    rows = [
        {
            "id_tipo_antecedente": 2,
            "nombre": "Lista OFAC",
            "categoria": "Critico",
            "puede_impedir_vinculacion": True,
        },
        {
            "id_tipo_antecedente": 3,
            "nombre": "Verificación adicional",
            "categoria": "EnRevision",
            "puede_impedir_vinculacion": False,
        },
    ]

    monkeypatch.setattr(
        repository,
        "listar_tipos_antecedente",
        lambda conn: rows,
    )

    response = client.get("/api/v1/catalogos/tipos-antecedente")

    assert response.status_code == 200
    assert response.json() == [
        {
            "idTipoAntecedente": 2,
            "nombre": "Lista OFAC",
            "categoria": "Critico",
            "puedeImpedirVinculacion": True,
        },
        {
            "idTipoAntecedente": 3,
            "nombre": "Verificación adicional",
            "categoria": "EnRevision",
            "puedeImpedirVinculacion": False,
        },
    ]


def test_tipos_antecedente_sin_datos(client, monkeypatch):
    monkeypatch.setattr(
        repository,
        "listar_tipos_antecedente",
        lambda conn: [],
    )

    response = client.get("/api/v1/catalogos/tipos-antecedente")

    assert response.status_code == 200
    assert response.json() == []


def test_tipos_antecedente_sql_filtra_y_ordena(monkeypatch):
    from unittest.mock import MagicMock

    conn = MagicMock()
    conn.execute.return_value.mappings.return_value = []

    repository.listar_tipos_antecedente(conn)

    sql = str(conn.execute.call_args.args[0])

    assert "FROM Catalogo.TipoAntecedente" in sql
    assert "WHERE Estado = 'Activo'" in sql
    assert "ORDER BY Categoria, Nombre" in sql
