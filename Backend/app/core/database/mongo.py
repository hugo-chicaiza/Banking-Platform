"""Cliente de MongoDB compartido (Azure Cosmos DB for MongoDB vCore o Atlas).

Un solo MongoClient por proceso y URI: pymongo ya maneja el pool. Nunca conecta sin
MONGO_URI; la URI (con su contraseña) no se registra en logs.
"""

from functools import lru_cache
from typing import Any

from app.core.config.settings import get_settings

_TIMEOUT_MS = 5000


@lru_cache
def _cliente(uri: str) -> Any:
    from pymongo import MongoClient

    return MongoClient(uri, serverSelectionTimeoutMS=_TIMEOUT_MS, tz_aware=True)


def coleccion(nombre: str) -> Any | None:
    """La colección `nombre` de MONGO_DB, o None si no hay MONGO_URI."""
    s = get_settings()
    uri = s.mongo_uri.get_secret_value()
    if not uri:
        return None
    return _cliente(uri)[s.mongo_db][nombre]
