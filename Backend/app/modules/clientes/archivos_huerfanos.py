"""Recoge únicamente objetos de Clientes sin metadatos después del plazo de gracia."""

from datetime import UTC, datetime, timedelta
from json import dumps

from sqlalchemy import text

from app.core.database.db import get_engine
from app.core.database.mongo import coleccion
from app.core.documentos.almacen import COLECCION
from app.core.tareas.ejecutor import Conteo, TareaRechazada
from app.modules.clientes.archivos import ORIGEN

_GRACIA = timedelta(hours=24)
_LOTE = 200


def ejecutar() -> Conteo:
    destino = coleccion(COLECCION)
    if destino is None:
        raise TareaRechazada("Almacenamiento de archivos sin configurar")
    filtro = {"origen": ORIGEN, "creadoEn": {"$lt": datetime.now(UTC) - _GRACIA}}
    conteo = Conteo()
    with (
        get_engine("cooperativa").connect() as conn,
        destino.find(filtro, {"_id": 1}).batch_size(_LOTE) as cursor,
    ):
        while lote := [doc["_id"] for doc in cursor.to_list(_LOTE)]:
            # El parámetro es una lista JSON acotada. Las versiones históricas
            # también cuentan como referencias y quedan fuera de la limpieza.
            referidos = set(
                conn.execute(
                    text("""
                SELECT a.ClaveAlmacenamiento
                FROM OPENJSON(:lote) WITH (clave varchar(200) '$') AS m
                JOIN Clientes.ClienteArchivo a ON a.ClaveAlmacenamiento=m.clave
            """),
                    {"lote": dumps(lote)},
                ).scalars()
            )
            conn.rollback()
            conteo.procesados += len(lote)
            huerfanos = [clave for clave in lote if clave not in referidos]
            if huerfanos:
                eliminados = destino.delete_many({**filtro, "_id": {"$in": huerfanos}})
                conteo.modificados += eliminados.deleted_count
    return conteo
