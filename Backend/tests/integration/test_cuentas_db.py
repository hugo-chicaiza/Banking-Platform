"""Pruebas de integración para CTA-01 contra CooperativaDB.

Se omiten si la BD no está configurada (p. ej. en CI sin secretos).
Estos tests validan que las tablas y columnas referenciadas en el
repositorio existen y tienen la estructura esperada.

NO se realiza ningún INSERT definitivo: las pruebas usan ROLLBACK o
validan solo la existencia de filas de referencia.
"""

import pytest

from app.core.config import get_settings
from app.core.db import get_engine
from app.modules.cuentas import repository

pytestmark = pytest.mark.skipif(
    not get_settings().cooperativa_db_server,
    reason="CooperativaDB no configurada",
)


@pytest.fixture(scope="module")
def conn():
    with get_engine("cooperativa").connect() as c:
        yield c


# ---------------------------------------------------------------------------
# Validar que las tablas/vistas tienen las columnas esperadas
# ---------------------------------------------------------------------------


def test_tabla_cliente_tiene_columnas(conn):
    """Clientes.Cliente debe tener IdCliente y Estado."""
    from sqlalchemy import text

    row = conn.execute(
        text(
            """
            SELECT COUNT(*) AS cnt
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = 'Clientes'
              AND TABLE_NAME   = 'Cliente'
              AND COLUMN_NAME IN ('IdCliente', 'Estado')
            """
        )
    ).scalar_one()
    assert row == 2, "Clientes.Cliente no tiene IdCliente o Estado"


def test_tabla_riesgo_cliente_tiene_columnas(conn):
    """Clientes.RiesgoCliente debe tener IdCliente, Estado y Vigente."""
    from sqlalchemy import text

    row = conn.execute(
        text(
            """
            SELECT COUNT(*) AS cnt
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = 'Clientes'
              AND TABLE_NAME   = 'RiesgoCliente'
              AND COLUMN_NAME IN ('IdCliente', 'Estado', 'Vigente')
            """
        )
    ).scalar_one()
    assert row == 3, "Clientes.RiesgoCliente no tiene las columnas esperadas"


def test_tabla_producto_tiene_columnas(conn):
    """ProductosFinancieros.Producto debe tener IdProducto, TipoProducto, Estado y MontoAperturaMinimo."""
    from sqlalchemy import text

    row = conn.execute(
        text(
            """
            SELECT COUNT(*) AS cnt
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = 'ProductosFinancieros'
              AND TABLE_NAME   = 'Producto'
              AND COLUMN_NAME IN ('IdProducto', 'TipoProducto', 'Estado', 'MontoAperturaMinimo')
            """
        )
    ).scalar_one()
    assert row == 4, "ProductosFinancieros.Producto no tiene las columnas esperadas"


def test_tabla_agencia_tiene_columna_estado(conn):
    """Organizacion.Agencia debe tener Codigo y Estado."""
    from sqlalchemy import text

    row = conn.execute(
        text(
            """
            SELECT COUNT(*) AS cnt
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = 'Organizacion'
              AND TABLE_NAME   = 'Agencia'
              AND COLUMN_NAME IN ('Codigo', 'Estado')
            """
        )
    ).scalar_one()
    assert row == 2, "Organizacion.Agencia no tiene Codigo o Estado"


def test_tabla_cuenta_tiene_columnas(conn):
    """Cuentas.Cuenta debe tener las columnas clave para CTA-01."""
    from sqlalchemy import text

    columnas = [
        "IdCuenta",
        "NumeroCuenta",
        "IdCliente",
        "IdProducto",
        "IdAgencia",
        "TipoCuenta",
        "IdMoneda",
        "Saldo",
        "SaldoRetenido",
        "Estado",
    ]
    row = conn.execute(
        text(
            """
            SELECT COUNT(*) AS cnt
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = 'Cuentas'
              AND TABLE_NAME   = 'Cuenta'
              AND COLUMN_NAME IN :cols
            """
        ),
        {"cols": tuple(columnas)},
    ).scalar_one()
    assert row == len(columnas), (
        f"Cuentas.Cuenta no tiene todas las columnas esperadas ({row}/{len(columnas)})"
    )


def test_sp_abrir_cuenta_existe(conn):
    """Cuentas.usp_AbrirCuenta debe existir en la base de datos."""
    from sqlalchemy import text

    row = conn.execute(
        text(
            """
            SELECT COUNT(*) AS cnt
            FROM sys.objects
            WHERE object_id = OBJECT_ID('Cuentas.usp_AbrirCuenta')
              AND type IN ('P', 'PC')
            """
        )
    ).scalar_one()
    assert row == 1, "Cuentas.usp_AbrirCuenta no existe"


# ---------------------------------------------------------------------------
# Lectura real del repositorio (sin escribir nada)
# ---------------------------------------------------------------------------


def test_obtener_cliente_inexistente_devuelve_none(conn):
    result = repository.obtener_cliente(conn, id_cliente=-999)
    assert result is None


def test_obtener_agencia_inexistente_devuelve_none(conn):
    result = repository.obtener_agencia(conn, id_agencia="ZZZ")
    assert result is None
