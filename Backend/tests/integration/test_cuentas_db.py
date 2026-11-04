"""Pruebas de integración para CTA-01 contra CooperativaDB.

Se omiten si la BD no está configurada (p. ej. en CI sin secretos).
Estos tests validan que las tablas y columnas referenciadas en el
repositorio existen y tienen la estructura esperada.

NO se realiza ningún INSERT definitivo: las pruebas usan ROLLBACK o
validan solo la existencia de filas de referencia.
"""

import pytest

from app.core.config.settings import get_settings
from app.core.database.db import get_engine
from app.modules.cuentas import repository
from app.modules.cuentas.schemas import ID_MONEDA_USD

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
    """RiesgoCliente expone el resultado y la vigencia usados por CTA-01."""
    from sqlalchemy import text

    row = conn.execute(
        text(
            """
            SELECT COUNT(*) AS cnt
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = 'Clientes'
              AND TABLE_NAME   = 'RiesgoCliente'
              AND COLUMN_NAME IN (
                  'IdCliente', 'ResultadoEvaluacion', 'EsVigente'
              )
            """
        )
    ).scalar_one()
    assert row == 3, "Clientes.RiesgoCliente no tiene las columnas esperadas"


def test_tabla_producto_tiene_columnas(conn):
    """Producto aporta el tipo de cuenta usado por las lecturas de A-02."""
    from sqlalchemy import text

    row = conn.execute(
        text(
            """
            SELECT COUNT(*) AS cnt
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = 'ProductosFinancieros'
              AND TABLE_NAME   = 'Producto'
              AND COLUMN_NAME IN (
                  'IdProducto', 'TipoProducto', 'Estado',
                  'MontoAperturaMinimo', 'TipoCuenta'
              )
            """
        )
    ).scalar_one()
    assert row == 5, "ProductosFinancieros.Producto no tiene las columnas esperadas"


def test_tabla_agencia_tiene_columna_estado(conn):
    """Organizacion.Agencia debe tener la clave usada por Cuenta y su Estado."""
    from sqlalchemy import text

    row = conn.execute(
        text(
            """
            SELECT COUNT(*) AS cnt
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = 'Organizacion'
              AND TABLE_NAME   = 'Agencia'
              AND COLUMN_NAME IN ('IdAgencia', 'Estado')
            """
        )
    ).scalar_one()
    assert row == 2, "Organizacion.Agencia no tiene IdAgencia o Estado"


def test_tabla_cuenta_tiene_columnas(conn):
    """Cuentas.Cuenta contiene los datos persistidos; moneda y tipo se derivan."""
    from sqlalchemy import text

    columnas = [
        "IdCuenta",
        "NumeroCuenta",
        "IdCliente",
        "IdProducto",
        "IdSubProducto",
        "IdAgencia",
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
              AND TABLE_NAME = 'Cuenta'
              AND COLUMN_NAME IN (
                  'IdCuenta', 'NumeroCuenta', 'IdCliente', 'IdProducto',
                  'IdSubProducto', 'IdAgencia', 'Saldo', 'SaldoRetenido', 'Estado'
              )
            """
        )
    ).scalar_one()
    assert row == len(columnas), (
        f"Cuentas.Cuenta no tiene todas las columnas esperadas ({row}/{len(columnas)})"
    )


def test_moneda_usd_es_regla_global_y_no_columna_de_cuenta(conn):
    """USD 840 pertenece al contrato, no se repite en cada fila de Cuenta."""
    from sqlalchemy import text

    row = conn.execute(
        text(
            """
            SELECT COUNT(*) AS cnt
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = 'Cuentas'
              AND TABLE_NAME = 'Cuenta'
              AND COLUMN_NAME = 'IdMoneda'
            """
        )
    ).scalar_one()
    assert row == 0
    assert ID_MONEDA_USD == 840


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


def test_sp_abrir_cuenta_tiene_firma_esperada(conn):
    """La llamada del repositorio debe coincidir con los parámetros reales."""
    from sqlalchemy import text

    rows = conn.execute(
        text(
            """
            SELECT p.name
            FROM sys.parameters AS p
            WHERE p.object_id = OBJECT_ID('Cuentas.usp_AbrirCuenta')
            ORDER BY p.parameter_id
            """
        )
    ).scalars()
    assert list(rows) == [
        "@IdCliente",
        "@IdSubProducto",
        "@IdAgencia",
        "@NumeroCuenta",
        "@MontoInicial",
        "@CreadoPor",
        "@IdCuenta",
    ]


# ---------------------------------------------------------------------------
# Lectura real del repositorio (sin escribir nada)
# ---------------------------------------------------------------------------


def test_obtener_cliente_inexistente_devuelve_none(conn):
    result = repository.obtener_cliente(conn, id_cliente=-999)
    assert result is None


def test_obtener_agencia_inexistente_devuelve_none(conn):
    result = repository.obtener_agencia(conn, id_agencia="ZZZ")
    assert result is None
