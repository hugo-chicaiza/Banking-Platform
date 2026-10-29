from collections.abc import Iterator
from functools import lru_cache
from typing import Literal

from sqlalchemy import URL, Connection, Engine, create_engine

from app.core.config import get_settings

DbName = Literal["cooperativa", "seguridad"]


@lru_cache
def get_engine(db: DbName) -> Engine:
    url = URL.create(
        "mssql+pyodbc",
        query={"odbc_connect": get_settings().odbc_connection_string(db)},
    )
    return create_engine(url, pool_pre_ping=True)


def cooperativa() -> Iterator[Connection]:
    """Dependencia FastAPI: una conexión a CooperativaDB por request."""
    with get_engine("cooperativa").connect() as conn:
        yield conn
