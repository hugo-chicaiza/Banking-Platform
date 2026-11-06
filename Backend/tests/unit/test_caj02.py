"""Pruebas unitarias de CAJ-02."""

from datetime import date, datetime
from decimal import Decimal
from unittest.mock import Mock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.core.database.db import cooperativa
from app.core.security.auth import usuario_actual
from app.modules.caja import repository, service
from app.modules.caja.router import router as caja_router
from tests.sesion import usuario_con_roles

FILA_JORNADA = {
    "IdJornadaCaja": 10,
    "IdUsuario": 25,
    "IdCajaFisica": 3,
    "IdAgencia": "001",
    "FechaHoraApertura": datetime(2026, 11, 5, 8, 0),
    "FechaHoraCierre": None,
    "DineroInicial": Decimal("100.00"),
    "Estado": "ABIERTA",
    "Observacion": None,
}


@pytest.fixture
def client(monkeypatch):
    app = FastAPI()
    app.include_router(caja_router, prefix="/api/v1")

    # Simular una sesión válida con un rol autorizado para CAJ-02
    app.dependency_overrides[usuario_actual] = lambda: usuario_con_roles("SUPERVISOR")

    # Evitar conexión real con Azure SQL
    app.dependency_overrides[cooperativa] = lambda: Mock()

    def consulta_falsa(conn, **kwargs):
        return service.PageJornada(
            items=[],
            page=kwargs["page"],
            page_size=kwargs["page_size"],
            total=0,
        )

    monkeypatch.setattr(service, "listar_jornadas", consulta_falsa)

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def test_caj02_respuesta_vacia(client):
    response = client.get("/api/v1/caja/jornadas")

    assert response.status_code == 200
    assert response.json() == {
        "items": [],
        "page": 1,
        "pageSize": 20,
        "total": 0,
    }


def test_caj02_paginacion(client):
    response = client.get("/api/v1/caja/jornadas?page=2&pageSize=10")

    assert response.status_code == 200
    assert response.json()["page"] == 2
    assert response.json()["pageSize"] == 10


@pytest.mark.parametrize(
    "query",
    [
        "page=0",
        "pageSize=0",
        "pageSize=101",
        "idUsuario=0",
        "estado=INVALIDO",
        "idAgencia=ABC",
        "desde=no-es-fecha",
        "parametroDesconocido=1",
        "page=1&page=2",
    ],
)
def test_caj02_parametros_invalidos(client, query):
    response = client.get(f"/api/v1/caja/jornadas?{query}")

    assert response.status_code == 400
    assert response.json()["status"] == 400
    assert response.json()["code"] in {
        "DATOS_INVALIDOS",
        "PARAMETRO_INVALIDO",
    }


def test_caj02_modelo_jornada():
    jornada = service._jornada(FILA_JORNADA)

    resultado = jornada.model_dump(by_alias=True, mode="json")

    assert resultado["idJornadaCaja"] == 10
    assert resultado["idAgencia"] == "001"
    assert resultado["dineroInicial"] == 100.0
    assert resultado["estado"] == "ABIERTA"
    assert resultado["fechaHoraCierre"] is None


def test_caj02_rango_fechas_invalido():
    with pytest.raises(HTTPException) as error:
        service.listar_jornadas(
            Mock(),
            id_agencia=None,
            id_usuario=None,
            estado=None,
            desde=date(2026, 11, 6),
            hasta=date(2026, 11, 5),
            page=1,
            page_size=20,
            sort="fechaHoraApertura,desc",
        )

    assert error.value.status_code == 400
    assert error.value.detail == {
        "code": "RANGO_FECHAS_INVALIDO",
        "message": "La fecha desde no puede ser posterior a hasta.",
    }


@pytest.mark.parametrize(
    "sort",
    [
        "campoInexistente,asc",
        "fechaHoraApertura,INVALIDO",
        "fechaHoraApertura;DROP TABLE,desc",
        "fechaHoraApertura",
    ],
)
def test_caj02_orden_invalido(sort):
    with pytest.raises(HTTPException) as error:
        service.listar_jornadas(
            Mock(),
            id_agencia=None,
            id_usuario=None,
            estado=None,
            desde=None,
            hasta=None,
            page=1,
            page_size=20,
            sort=sort,
        )

    assert error.value.status_code == 400
    assert error.value.detail == {
        "code": "ORDEN_INVALIDO",
        "message": "El ordenamiento solicitado no es válido.",
    }


def test_caj02_repositorio_parametrizado():
    conn = Mock()

    total_resultado = Mock()
    total_resultado.scalar_one.return_value = 1

    filas_resultado = Mock()
    filas_resultado.mappings.return_value = [FILA_JORNADA]

    conn.execute.side_effect = [
        total_resultado,
        filas_resultado,
    ]

    filas, total = repository.listar_jornadas(
        conn,
        id_agencia="001",
        id_usuario=25,
        estado="ABIERTA",
        desde=date(2026, 11, 1),
        hasta=date(2026, 11, 5),
        page=1,
        page_size=20,
        sort="fechaHoraApertura,desc",
    )

    assert total == 1
    assert len(filas) == 1

    primera = conn.execute.call_args_list[0]
    segunda = conn.execute.call_args_list[1]

    assert primera.args[1]["id_agencia"] == "001"
    assert segunda.args[1]["page_size"] == 20
    assert segunda.args[1]["offset"] == 0

    sql = str(segunda.args[0])
    assert "FROM Caja.JornadasCaja" in sql
    assert "ORDER BY FechaHoraApertura DESC" in sql
    assert "OFFSET :offset ROWS" in sql
    assert "FETCH NEXT :page_size ROWS ONLY" in sql


def test_caj02_filtros_service(monkeypatch):
    recibidos = {}

    def consulta_falsa(conn, **kwargs):
        recibidos.update(kwargs)
        return [FILA_JORNADA], 1

    monkeypatch.setattr(repository, "listar_jornadas", consulta_falsa)

    resultado = service.listar_jornadas(
        Mock(),
        id_agencia="001",
        id_usuario=25,
        estado="ABIERTA",
        desde=None,
        hasta=None,
        page=2,
        page_size=10,
        sort="fechaHoraApertura,desc",
    )

    assert resultado.total == 1
    assert resultado.page == 2
    assert resultado.page_size == 10
    assert len(resultado.items) == 1
    assert recibidos["id_agencia"] == "001"
    assert recibidos["id_usuario"] == 25
