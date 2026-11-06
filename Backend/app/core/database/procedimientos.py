"""Ejecución de procedimientos de SQL Server con parámetros de salida (INOUT).

`conn.execute(text("EXEC ..."))` no devuelve los OUTPUT. El patrón es un lote que
declara variables, ejecuta el procedimiento con `OUTPUT` y termina con un SELECT de
esas variables. Si el procedimiento devuelve sus propios conjuntos de resultados, se
avanza con nextset() hasta el último, que es el SELECT del lote.

Va por el cursor DBAPI de la misma conexión, así que comparte la transacción abierta
con `conn.begin()`. Los errores se envuelven en DBAPIError para que
ProblemDetailsRoute traduzca los THROW 5xxxx igual que en el resto de la API.
"""

from collections.abc import Sequence
from typing import Any

from sqlalchemy import Connection
from sqlalchemy.exc import DBAPIError


def ejecutar_con_salidas(
    conn: Connection, lote: str, parametros: Sequence[Any]
) -> dict[str, Any]:
    """Ejecuta `lote` (marcadores `?`) y devuelve la última fila del último resultado."""
    error_dbapi: type[Exception] = conn.dialect.loaded_dbapi.Error
    cursor = conn.connection.cursor()
    ultima: dict[str, Any] | None = None
    try:
        cursor.execute(lote, tuple(parametros))
        while True:
            if cursor.description:
                columnas = [columna[0] for columna in cursor.description]
                filas = cursor.fetchall()
                if filas:
                    ultima = dict(zip(columnas, filas[-1], strict=True))
            if not cursor.nextset():
                break
    except error_dbapi as exc:
        raise DBAPIError.instance(
            None, None, exc, error_dbapi, hide_parameters=True
        ) from exc
    finally:
        cursor.close()
    if ultima is None:
        raise RuntimeError("El procedimiento no devolvió sus parámetros de salida")
    return ultima
