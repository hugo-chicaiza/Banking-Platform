from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.core.db import cooperativa
from app.main import app
from app.modules.clientes import repository


@pytest.fixture
def client():
    app.dependency_overrides[cooperativa] = lambda: None

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def test_listar_clientes_sin_resultados(client, monkeypatch):
    monkeypatch.setattr(
        repository,
        "listar_clientes",
        lambda conn, **kwargs: {
            "items": [],
            "page": kwargs["page"],
            "page_size": kwargs["page_size"],
            "total": 0,
        },
    )

    response = client.get("/api/v1/clientes")

    assert response.status_code == 200
    assert response.json() == {
        "items": [],
        "page": 1,
        "pageSize": 20,
        "total": 0,
    }


def test_listar_clientes_filtros_y_paginacion(client, monkeypatch):
    recibidos = {}

    def fake_listar(conn, **kwargs):
        recibidos.update(kwargs)
        return {
            "items": [],
            "page": kwargs["page"],
            "page_size": kwargs["page_size"],
            "total": 0,
        }

    monkeypatch.setattr(repository, "listar_clientes", fake_listar)

    response = client.get(
        "/api/v1/clientes",
        params={
            "q": "Maria",
            "identificacion": "1712345678",
            "tipoCliente": "Natural",
            "estado": "Activo",
            "page": 2,
            "pageSize": 10,
            "sort": "nombres,asc",
        },
    )

    assert response.status_code == 200
    assert recibidos == {
        "q": "Maria",
        "identificacion": "1712345678",
        "tipo_cliente": "Natural",
        "estado": "Activo",
        "page": 2,
        "page_size": 10,
        "sort": "nombres,asc",
    }


def test_listar_clientes_sort_invalido(client, monkeypatch):
    monkeypatch.setattr(
        repository,
        "listar_clientes",
        lambda conn, **kwargs: (_ for _ in ()).throw(
            ValueError("Campo de ordenamiento no permitido")
        ),
    )

    response = client.get(
        "/api/v1/clientes",
        params={"sort": "password,asc"},
    )

    assert response.status_code == 400


def test_repository_filtra_y_pagina():
    conn = MagicMock()

    conn.execute.return_value.scalar_one.return_value = 0
    conn.execute.return_value.mappings.return_value.all.return_value = []

    resultado = repository.listar_clientes(
        conn,
        q="Maria",
        identificacion="1712345678",
        tipo_cliente="Natural",
        estado="Activo",
        page=2,
        page_size=10,
        sort="nombres,asc",
    )

    assert resultado == {
        "items": [],
        "page": 2,
        "page_size": 10,
        "total": 0,
    }

    assert conn.execute.call_count == 2

    consultas = [str(call.args[0]) for call in conn.execute.call_args_list]

    assert all("c.Nombres LIKE :q" in sql for sql in consultas)
    assert all("c.Identificacion = :identificacion" in sql for sql in consultas)
    assert all("c.TipoCliente = :tipo_cliente" in sql for sql in consultas)
    assert all("c.Estado = :estado" in sql for sql in consultas)

    assert "ORDER BY c.Nombres ASC" in consultas[1]
    assert "OFFSET :offset ROWS" in consultas[1]

    params = conn.execute.call_args_list[1].args[1]
    assert params["offset"] == 10
    assert params["page_size"] == 10


def test_repository_rechaza_sort_no_permitido():
    conn = MagicMock()

    with pytest.raises(ValueError):
        repository.listar_clientes(
            conn,
            sort="password,asc",
        )

    conn.execute.assert_not_called()
