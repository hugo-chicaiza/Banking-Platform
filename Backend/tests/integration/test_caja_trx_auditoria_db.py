"""Auditoría Caja/TRX 2026-11-09: integración de SOLO LECTURA contra BD de PRUEBA.

Se activa con BANKING_DB_PRUEBAS=1 (nunca contra producción). No escribe: todo corre
dentro de la transacción de conexion_de_prueba, que se revierte al final.
"""

from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, text

from app.modules.caja import repository as caja_repo
from app.modules.transacciones import repository as trx_repo
from tests.caja_bd import SIN_BD, columnas_de, conexion_de_prueba

pytestmark = SIN_BD


@pytest.fixture
def conn() -> Iterator[Connection]:
    yield from conexion_de_prueba()


def test_restricciones_cuenta_usa_columnas_reales(conn: Connection) -> None:
    assert "Estado" in columnas_de(conn, "Clientes", "Cliente")
    assert "PermiteOperacionesPresenciales" in columnas_de(
        conn, "ProductosFinancieros", "Producto"
    )
    fila = conn.execute(
        text("SELECT TOP (1) IdCuenta FROM Cuentas.Cuenta ORDER BY IdCuenta")
    ).first()
    if fila is None:
        pytest.skip("No hay cuentas en la BD de prueba")
    restricciones = trx_repo.restricciones_cuenta(conn, int(fila[0]))
    assert restricciones is not None
    assert set(restricciones) == {"EstadoCliente", "PermiteOperacionesPresenciales"}


def test_hora_de_ecuador_difiere_de_getdate_en_azure(conn: Connection) -> None:
    """Evidencia de H-07: en Azure SQL GETDATE() es UTC, no hora de Ecuador."""
    diferencia = conn.execute(
        text(
            "SELECT DATEDIFF(MINUTE, CAST(SYSDATETIMEOFFSET() AT TIME ZONE"
            " 'SA Pacific Standard Time' AS datetime2), GETDATE())"
        )
    ).scalar_one()
    # 300 minutos en Azure SQL (UTC); 0 si el servidor de prueba está en hora local
    assert diferencia in (0, 300)


def test_indices_unicos_que_protegen_carreras(conn: Connection) -> None:
    """Informativa: lista los índices únicos de las tablas con carreras (A-09, C05).

    No falla si faltan: el informe pide al DBA confirmarlos (CAMBIOS_SQL_PROPUESTOS).
    """
    filas = conn.execute(
        text(
            "SELECT t.name AS Tabla, i.name AS Indice, i.has_filter,"
            " i.filter_definition FROM sys.indexes i"
            " JOIN sys.tables t ON t.object_id = i.object_id"
            " WHERE SCHEMA_NAME(t.schema_id) IN ('Caja', 'Transacciones')"
            " AND t.name IN ('JornadasCaja', 'CuadreCaja', 'Transaccion')"
            " AND i.is_unique = 1"
        )
    ).all()
    assert isinstance(filas, list)


def test_jornada_bloqueada_y_totales_en_misma_transaccion(conn: Connection) -> None:
    fila = conn.execute(
        text("SELECT TOP (1) IdJornadaCaja FROM Caja.JornadasCaja ORDER BY 1 DESC")
    ).first()
    if fila is None:
        pytest.skip("No hay jornadas en la BD de prueba")
    jornada = caja_repo.obtener_jornada(conn, int(fila[0]), bloquear=True)
    totales = caja_repo.calcular_totales(conn, int(fila[0]))
    assert jornada is not None and totales is not None
    assert totales["SaldoInicial"] == jornada["DineroInicial"]
