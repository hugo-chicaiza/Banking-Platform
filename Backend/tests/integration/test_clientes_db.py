"""CLI-02 contra SQL Server: identidades e historial, con rollback al terminar."""

from collections.abc import Iterator
from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import Connection, text

from app.core.config.settings import get_settings
from app.core.database.db import get_engine
from app.modules.clientes import repository
from app.modules.clientes.schemas import ClienteCreate, DireccionCreate
from tests.sesion import ID_AUDITORIA

pytestmark = pytest.mark.skipif(
    not get_settings().cooperativa_db_server, reason="CooperativaDB no configurada"
)


@pytest.fixture
def conn() -> Iterator[Connection]:
    with get_engine("cooperativa").connect() as conexion:
        nocount = conexion.exec_driver_sql("SELECT @@OPTIONS & 512").scalar_one()
        # Reproducir una sesión que devuelve los conteos de los INSERT antes del SELECT.
        conexion.exec_driver_sql("SET NOCOUNT OFF;").close()
        try:
            yield conexion
        finally:
            conexion.rollback()
            conexion.exec_driver_sql(
                "SET NOCOUNT ON;" if nocount else "SET NOCOUNT OFF;"
            ).close()
            conexion.rollback()


def test_cli02_recupera_identidades_y_guarda_historial(conn: Connection):
    ciudad = (
        conn.execute(
            text(
                "SELECT TOP 1 IdCiudad, CodigoPais FROM Catalogo.Ciudad ORDER BY IdCiudad"
            )
        )
        .mappings()
        .first()
    )
    if ciudad is None:
        pytest.skip("Se necesita una ciudad del catálogo para crear el cliente")

    payload = ClienteCreate(
        identificacion=f"T{uuid4().hex[:12]}",
        tipo_documento="P",
        tipo_cliente="Natural",
        nombres="Prueba integración",
        apellidos="Cliente temporal",
        fecha_nacimiento=date(1990, 1, 1),
        genero="F",
        estado_civil="Soltero",
        codigo_pais_nacionalidad=ciudad["CodigoPais"],
        telefono_celular="0990000000",
        email="prueba@example.com",
        consentimiento_datos=True,
        direccion=DireccionCreate(
            codigo_pais=ciudad["CodigoPais"],
            id_ciudad=ciudad["IdCiudad"],
            calle_direccion="Calle de prueba",
            referencia_ubicacion="Prueba de integración",
        ),
    )
    cliente = repository.crear_cliente(
        conn, payload=payload, creado_por=ID_AUDITORIA, direccion_ip="127.0.0.1"
    )

    assert cliente["id_cliente"] > 0
    assert cliente["direcciones"][0]["id_direccion"] > 0
    fila = (
        conn.execute(
            text("""
            SELECT c.Identificacion, c.Estado, c.CreadoPor, d.IdDireccion,
                   d.CreadoPor AS CreadoPorDireccion, d.IdCiudad, d.EsPrincipal,
                   h.TipoOperacion, h.ModificadoPor
            FROM Clientes.Cliente AS c
            JOIN Clientes.Direcciones AS d ON d.IdCliente = c.IdCliente
            JOIN Clientes.ClientesHis AS h ON h.IdCliente = c.IdCliente
            WHERE c.IdCliente = :id_cliente AND h.CampoModificado = 'CREACION'
        """),
            {"id_cliente": cliente["id_cliente"]},
        )
        .mappings()
        .one()
    )

    assert fila["Identificacion"] == payload.identificacion
    assert fila["Estado"] == cliente["estado"] == "Pendiente"
    assert fila["IdDireccion"] == cliente["direcciones"][0]["id_direccion"]
    assert fila["IdCiudad"] == payload.direccion.id_ciudad
    assert fila["EsPrincipal"]
    assert fila["TipoOperacion"] == "I"
    assert fila["CreadoPor"] == fila["ModificadoPor"] == ID_AUDITORIA
    assert fila["CreadoPorDireccion"] == ID_AUDITORIA


def _cliente_con_direccion(conn: Connection) -> tuple[int, str]:
    fila = conn.execute(
        text(
            """
            SELECT TOP 1 c.IdCliente, c.Identificacion
            FROM Clientes.Cliente AS c
            WHERE EXISTS (SELECT 1 FROM Clientes.Direcciones AS d
                          WHERE d.IdCliente = c.IdCliente AND d.Estado = 'Activo')
            ORDER BY c.IdCliente
            """
        )
    ).first()
    if fila is None:
        pytest.skip("Se necesita un cliente con dirección activa")
    return fila[0], fila[1]


def test_consultas_de_direcciones_derivan_el_pais_de_la_ciudad(conn: Connection):
    """CLI-03, CLI-04 y CLI-09: Direcciones ya no tiene CodigoPais (sale de la ciudad)."""
    id_cliente, identificacion = _cliente_con_direccion(conn)

    filas, total = repository.consultar_clientes(conn, identificacion=identificacion)
    assert total == 1 and filas[0]["id_cliente"] == id_cliente

    detalle = repository.obtener_cliente_detalle(conn, id_cliente)
    assert detalle is not None

    direcciones = repository.listar_direcciones(conn, id_cliente)
    assert direcciones
    paises: dict[int, str] = {
        fila[0]: fila[1]
        for fila in conn.execute(
            text("SELECT IdCiudad, CodigoPais FROM Catalogo.Ciudad")
        )
    }
    for direccion in direcciones:
        assert direccion["codigo_pais"] == paises[direccion["id_ciudad"]]


def test_alta_y_cambio_de_direccion_sin_codigo_pais(conn: Connection):
    """CLI-10 y CLI-11 escriben la dirección sin la columna eliminada."""
    id_cliente, _ = _cliente_con_direccion(conn)
    id_ciudad, codigo_pais = conn.execute(
        text("SELECT TOP 1 IdCiudad, CodigoPais FROM Catalogo.Ciudad ORDER BY IdCiudad")
    ).one()

    nueva = repository.insertar_direccion(
        conn,
        id_cliente,
        {
            "tipo_direccion": "Trabajo",
            "codigo_pais": codigo_pais,
            "id_ciudad": id_ciudad,
            "calle_direccion": "Av. Prueba 123",
            "referencia_ubicacion": "Frente al parque",
        },
        modificado_por=ID_AUDITORIA,
        direccion_ip="127.0.0.1",
    )
    assert nueva["codigo_pais"] == codigo_pais

    actualizada = repository.actualizar_direccion(
        conn,
        id_cliente,
        nueva["id_direccion"],
        {"calle_direccion": "Av. Prueba 456"},
        modificado_por=ID_AUDITORIA,
        direccion_ip="127.0.0.1",
        valores_anteriores=nueva,
    )
    assert actualizada["calle_direccion"] == "Av. Prueba 456"
    assert actualizada["codigo_pais"] == codigo_pais
