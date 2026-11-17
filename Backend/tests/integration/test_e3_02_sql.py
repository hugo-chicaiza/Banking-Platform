"""E3-02 en SQL real, opt-in y rollback. No usa sesiones simuladas ni DDL.

Solo crea filas Q375 con UUID dentro de la transaccion de cada prueba.
No prueba autenticacion HTTP: los endpoints deben verificarse con WorkOS real.
"""

import os
from decimal import Decimal
from typing import cast
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.config.settings import get_settings
from app.core.database.db import get_engine
from app.modules.catalogos import repository as catalogos
from app.modules.productos import repository as repo
from app.modules.productos import service

pytestmark = pytest.mark.skipif(
    os.getenv("E302_SQL_PRUEBAS") != "1",
    reason="E3-02 SQL real requiere autorizacion E302_SQL_PRUEBAS=1",
)


@pytest.fixture
def conn():
    s = get_settings()
    assert s.app_env == "development"
    assert s.cooperativa_db_server == os.environ["E302_SQL_EXPECTED_SERVER"]
    assert s.cooperativa_db_name == os.environ["E302_SQL_EXPECTED_DATABASE"]
    with get_engine("cooperativa").connect() as conexion:
        transaccion = conexion.begin()
        try:
            assert conexion.scalar(text("SELECT DB_NAME()")) == s.cooperativa_db_name
            yield conexion
        finally:
            transaccion.rollback()


@pytest.fixture
def producto(conn):
    datos = {
        "codigo_producto": "Q375" + uuid4().hex[:5].upper(),
        "nombre_producto": "E3-02 QA temporal con rollback",
        "descripcion": "Creado por Codex para E3-02; transaccion reversible",
        "tipo_producto": "Cuenta",
        "tipo_cuenta": "Ahorro",
        "monto_apertura_minimo": Decimal("10.00"),
        "id_tipo_credito": None,
        "id_red": None,
        "permite_operaciones_presenciales": True,
        "id_tipo_producto": 1,
    }
    id_ = repo.insertar_producto(conn, datos)
    return id_, datos


def test_e302_alta_y_edicion_borrador_sql(conn, producto):
    id_, datos = producto
    creado = service.obtener_producto(conn, id_)
    assert creado.estado_catalogo == "Borrador" and creado.estado == "I"
    repo.actualizar_producto(conn, id_, {"nombre_producto": "E3-02 QA editado"})
    assert service.obtener_producto(conn, id_).nombre_producto == "E3-02 QA editado"
    assert creado.codigo_producto == datos["codigo_producto"]


def test_e302_codigo_duplicado_sql_traduce_409(conn, producto):
    _, datos = producto
    with pytest.raises(DBAPIError) as error, conn.begin_nested():
        repo.insertar_producto(conn, datos)
    traducido = service._traducir(error.value)
    assert traducido.status_code == 409
    detalle = cast(dict[str, object], traducido.detail)
    assert detalle["code"] == "CODIGO_DUPLICADO"


def test_e302_ficha_y_edades_sql(conn, producto):
    id_, datos = producto
    sub = repo.insertar_subproducto(
        conn, id_, datos["codigo_producto"] + "-MN", "E3-02 QA menores", 0, 17
    )
    ficha = service.ficha_subproducto(conn, sub)
    assert ficha.subproducto.estado_catalogo == "Borrador"
    assert ficha.elegibilidad.edad_maxima == 17
    assert ficha.condiciones is None
    with pytest.raises(HTTPException) as error:
        service._validar_edades(18, 17)
    assert error.value.status_code == 422
    detalle = cast(dict[str, object], error.value.detail)
    assert detalle["code"] == "ELEGIBILIDAD_INVALIDA"


def test_e302_seleccion_y_elegibilidad_sql(conn, producto):
    id_, datos = producto
    menor = repo.insertar_subproducto(
        conn, id_, datos["codigo_producto"] + "-MN", "E3-02 QA menores", 0, 17
    )
    adulto = repo.insertar_subproducto(
        conn, id_, datos["codigo_producto"] + "-AD", "E3-02 QA adultos", 18, 120
    )
    assert all(
        p["id_producto"] != id_ for p in catalogos.listar_productos(conn, "Cuenta")
    )
    cliente = conn.scalar(
        text(
            "SELECT TOP(1) IdCliente FROM Clientes.Cliente WHERE TipoCliente='Natural' AND Estado='Activo' AND FechaNacimiento < '2000-01-01' ORDER BY IdCliente"
        )
    )
    if cliente is None:
        pytest.skip(
            "No existe cliente adulto activo para lectura; no se crean ni modifican clientes ajenos"
        )
    repo.actualizar_producto(conn, id_, {"estado": "A", "estado_catalogo": "Activo"})
    for sub in (menor, adulto):
        repo.actualizar_subproducto(
            conn, sub, {"estado": "A", "estado_catalogo": "Activo"}
        )
    assert service.cliente_elegible(conn, cliente, adulto)[0]
    elegible, motivos = service.cliente_elegible(conn, cliente, menor)
    assert not elegible and "EDAD_SUPERIOR_MAXIMA" in motivos
    filtrado = catalogos.listar_productos(conn, "Cuenta", edad=16)
    propios = next(p for p in filtrado if p["id_producto"] == id_)
    assert [s["id_sub_producto"] for s in propios["subproductos"]] == [menor]


def test_e302_borrar_solo_registros_propios_sql(conn, producto):
    id_, datos = producto
    repo.insertar_subproducto(
        conn, id_, datos["codigo_producto"] + "-MN", "E3-02 QA borrado", 0, 17
    )
    propio = repo.obtener_producto(conn, id_)
    assert propio is not None and propio["codigo_producto"].startswith("Q375")
    repo.eliminar_producto(conn, id_)
    assert repo.obtener_producto(conn, id_) is None
