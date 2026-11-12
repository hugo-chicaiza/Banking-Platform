"""ORG-01/02 contra una BD de PRUEBA (BANKING_DB_PRUEBAS=1; nunca producción).

Solo el repositorio: el service hace commit, y estas pruebas corren dentro de la
transacción de conexion_de_prueba, que se revierte al final.
"""

import threading
from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError

from app.core.database.db import get_engine
from app.modules.organizacion import repository as repo
from app.modules.organizacion import service
from tests.caja_bd import SIN_BD, columnas_de, conexion_de_prueba, escritura


def _codigo(exc: Any) -> str:
    detalle: Any = exc.detail
    return str(detalle["code"])


pytestmark = SIN_BD


@pytest.fixture
def conn() -> Iterator[Connection]:
    yield from conexion_de_prueba()


def test_columnas_y_restricciones_reales(conn: Connection) -> None:
    assert {
        "IdAgencia",
        "Codigo",
        "TipoAgencia",
        "Estado",
        "Telefono",
        "Direccion",
        "FechaCreacion",
        "IdCiudad",
        "KeyAgencia",
    } <= columnas_de(conn, "Organizacion", "Agencia")
    nombres = set(
        conn.execute(
            text(
                "SELECT name FROM sys.objects WHERE parent_object_id ="
                " OBJECT_ID('Organizacion.Agencia')"
                " UNION SELECT name FROM sys.indexes WHERE object_id ="
                " OBJECT_ID('Organizacion.Agencia')"
            )
        ).scalars()
    )
    # service._RESTRICCIONES depende de estos nombres
    assert set(service._RESTRICCIONES) <= nombres


def test_triggers_sobre_agencia(conn: Connection) -> None:
    """Informativa: si aparece un trigger, revisar que no contradiga las reglas."""
    triggers = list(
        conn.execute(
            text(
                "SELECT name FROM sys.triggers WHERE parent_id ="
                " OBJECT_ID('Organizacion.Agencia')"
            )
        ).scalars()
    )
    assert isinstance(triggers, list)


def test_lectura_y_dependencias_de_una_agencia_real(conn: Connection) -> None:
    fila = conn.execute(
        text("SELECT TOP (1) IdAgencia FROM Organizacion.Agencia ORDER BY IdAgencia")
    ).scalar()
    if fila is None:
        pytest.skip("No hay agencias en la BD de prueba")
    agencia = repo.obtener_agencia(conn, str(fila), bloquear=True)
    assert agencia is not None
    assert isinstance(repo.dependencias_activas(conn, str(fila)), list)


@escritura
def test_insertar_y_actualizar_se_revierte(conn: Connection) -> None:
    ciudad = conn.execute(text("SELECT TOP (1) IdCiudad FROM Catalogo.Ciudad")).scalar()
    libre = next(
        f"Z{n:02d}"
        for n in range(100)
        if repo.obtener_agencia(conn, f"Z{n:02d}") is None
    )
    repo.insertar_agencia(
        conn,
        {
            "id_agencia": libre,
            "codigo": f"TST-{libre}",
            "tipo_agencia": "Sucursal",
            "id_ciudad": ciudad,
            "telefono": None,
            "direccion": None,
            "key_agencia": None,
        },
    )
    creada = repo.obtener_agencia(conn, libre)
    assert creada is not None and creada["Estado"] == "A"
    assert repo.dependencias_activas(conn, libre) == []
    assert repo.actualizar_agencia(conn, libre, {"estado": "I"}) == 1
    assert repo.obtener_agencia(conn, libre)["Estado"] == "I"  # type: ignore[index]


@escritura
def test_segunda_matriz_la_rechaza_el_indice(conn: Connection) -> None:
    if (
        conn.execute(
            text("SELECT 1 FROM Organizacion.Agencia WHERE TipoAgencia = 'Matriz'")
        ).first()
        is None
    ):
        pytest.skip("La BD de prueba no tiene Matriz")
    ciudad = conn.execute(text("SELECT TOP (1) IdCiudad FROM Catalogo.Ciudad")).scalar()
    with pytest.raises(DBAPIError) as error, conn.begin_nested():
        repo.insertar_agencia(
            conn,
            {
                "id_agencia": "Z99",
                "codigo": "TST-MTZ",
                "tipo_agencia": "Matriz",
                "id_ciudad": ciudad,
                "telefono": None,
                "direccion": None,
                "key_agencia": None,
            },
        )
    assert _codigo(service.traducir_error_agencia(error.value)) == "MATRIZ_YA_EXISTE"


@escritura
def test_creaciones_concurrentes_del_mismo_codigo_se_serializan(
    conn: Connection,
) -> None:
    """La primera transacción bloquea el código; la segunda espera (LOCK_TIMEOUT)."""
    repo.conflictos_de_unicidad(
        conn, id_agencia="Z98", codigo="TST-CONC", key_agencia=None, matriz=False
    )
    resultado: dict[str, BaseException | None] = {"error": None}

    def segunda() -> None:
        with get_engine("cooperativa").connect() as otra, otra.begin():
            otra.execute(text("SET LOCK_TIMEOUT 1500"))
            try:
                repo.insertar_agencia(
                    otra,
                    {
                        "id_agencia": "Z97",
                        "codigo": "TST-CONC",
                        "tipo_agencia": "Sucursal",
                        "id_ciudad": otra.execute(
                            text("SELECT TOP (1) IdCiudad FROM Catalogo.Ciudad")
                        ).scalar(),
                        "telefono": None,
                        "direccion": None,
                        "key_agencia": None,
                    },
                )
            except DBAPIError as exc:  # 1222: tiempo de espera de bloqueo
                resultado["error"] = exc
            finally:
                otra.rollback()

    hilo = threading.Thread(target=segunda)
    hilo.start()
    hilo.join(10)
    assert resultado["error"] is not None
    assert "1222" in str(resultado["error"].orig)  # type: ignore[union-attr]
