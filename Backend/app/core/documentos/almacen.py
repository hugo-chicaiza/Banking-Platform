"""Dónde vive el contenido de los documentos (decisión P4-10: MongoDB).

`AlmacenDocumentos` es la interfaz; cambiar de proveedor cuesta un adaptador. El
contenido llega ya cifrado: el almacén no conoce la clave ni el nombre original.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

Analisis = Literal["Pendiente", "Limpio", "Rechazado"]
COLECCION = "documentos"


class ErrorAlmacen(Exception):
    """El almacén no responde. Los mensajes no llevan datos del documento."""


class DocumentoInexistente(Exception):
    """No hay documento con esa clave."""


@dataclass(frozen=True)
class Guardado:
    """Lo que el almacén devuelve al leer: el contenido cifrado y su estado."""

    contenido: bytes
    tipo_contenido: str
    analisis: Analisis


class AlmacenDocumentos(Protocol):
    def guardar(
        self,
        clave: str,
        contenido: bytes,
        *,
        tipo_contenido: str,
        tamano: int,
        sha256: str,
        origen: str,
        analisis: Analisis,
    ) -> None:
        """Inserta un documento nuevo; nunca sobrescribe (una clave ya usada falla)."""
        ...

    def leer(self, clave: str) -> Guardado:
        """DocumentoInexistente si no está."""
        ...

    def eliminar(self, clave: str) -> None:
        """Borra el documento si existe (compensación o limpieza de huérfanos)."""
        ...

    def marcar_analisis(self, clave: str, analisis: Analisis) -> None:
        """Resultado del análisis de malware."""
        ...


class AlmacenMongo:
    """Colección `documentos`, un documento por archivo (`_id` = clave generada).

    Archivos de hasta 5 MB: caben en un documento (límite de 16 MB), sin GridFS.
    """

    def __init__(self, coleccion: Any) -> None:
        self._coleccion = coleccion

    def guardar(
        self,
        clave: str,
        contenido: bytes,
        *,
        tipo_contenido: str,
        tamano: int,
        sha256: str,
        origen: str,
        analisis: Analisis,
    ) -> None:
        from pymongo.errors import PyMongoError

        try:
            self._coleccion.insert_one(
                {
                    "_id": clave,
                    "contenido": contenido,
                    "tipoContenido": tipo_contenido,
                    "tamano": tamano,
                    "sha256": sha256,
                    "origen": origen,
                    "analisis": analisis,
                    "creadoEn": datetime.now(UTC),
                }
            )
        except PyMongoError as exc:
            raise ErrorAlmacen(type(exc).__name__) from None

    def leer(self, clave: str) -> Guardado:
        from pymongo.errors import PyMongoError

        try:
            doc = self._coleccion.find_one(
                {"_id": clave}, {"contenido": 1, "tipoContenido": 1, "analisis": 1}
            )
        except PyMongoError as exc:
            raise ErrorAlmacen(type(exc).__name__) from None
        if doc is None:
            raise DocumentoInexistente()
        return Guardado(bytes(doc["contenido"]), doc["tipoContenido"], doc["analisis"])

    def eliminar(self, clave: str) -> None:
        from pymongo.errors import PyMongoError

        try:
            self._coleccion.delete_one({"_id": clave})
        except PyMongoError as exc:
            raise ErrorAlmacen(type(exc).__name__) from None

    def marcar_analisis(self, clave: str, analisis: Analisis) -> None:
        from pymongo.errors import PyMongoError

        try:
            resultado = self._coleccion.update_one(
                {"_id": clave},
                {"$set": {"analisis": analisis, "analizadoEn": datetime.now(UTC)}},
            )
        except PyMongoError as exc:
            raise ErrorAlmacen(type(exc).__name__) from None
        if resultado.matched_count == 0:
            raise DocumentoInexistente()


@dataclass
class AlmacenMemoria:
    """Adaptador falso para pruebas (y para correr sin MongoDB en una prueba local)."""

    documentos: dict[str, dict[str, Any]] = field(default_factory=dict)

    def guardar(
        self,
        clave: str,
        contenido: bytes,
        *,
        tipo_contenido: str,
        tamano: int,
        sha256: str,
        origen: str,
        analisis: Analisis,
    ) -> None:
        if clave in self.documentos:
            raise ErrorAlmacen("DuplicateKeyError")
        self.documentos[clave] = {
            "contenido": contenido,
            "tipoContenido": tipo_contenido,
            "tamano": tamano,
            "sha256": sha256,
            "origen": origen,
            "analisis": analisis,
        }

    def leer(self, clave: str) -> Guardado:
        doc = self.documentos.get(clave)
        if doc is None:
            raise DocumentoInexistente()
        return Guardado(doc["contenido"], doc["tipoContenido"], doc["analisis"])

    def eliminar(self, clave: str) -> None:
        self.documentos.pop(clave, None)

    def marcar_analisis(self, clave: str, analisis: Analisis) -> None:
        if clave not in self.documentos:
            raise DocumentoInexistente()
        self.documentos[clave]["analisis"] = analisis
