"""Guardar, leer y eliminar documentos (E5-08 #389, decisión P4-10).

Cómo se guarda un archivo:
1. Se valida: tamaño (máximo DOCUMENTOS_MAX_BYTES, 5 MB) y tipo por su contenido
   (PDF, JPG o PNG); el nombre o la extensión que mande el cliente no cuentan.
2. Se calcula su SHA-256 (para el registro y para detectar duplicados).
3. Se cifra con AES-256-GCM (DOCUMENTOS_CLAVE); el dato asociado ata el contenido a su
   clave, así no se puede servir el contenido de otro documento.
4. Se guarda en MongoDB bajo una clave generada (UUID), nunca el nombre original.
   Nunca se sobrescribe: reemplazar es guardar otro y versionar en la tabla del módulo.

Lo que sube un usuario se analiza antes de cifrar (analisis.py, OWASP ASVS 5.0 5.4.3):
`Rechazado` lanza ArchivoRechazado (422) y no se guarda nada; si pasa, se guarda
`Limpio`. Lo que genera el propio sistema (un PDF) nace `Limpio` sin analizar. `leer`
solo entrega `Limpio`; `Pendiente` queda para documentos anteriores o un análisis
asíncrono futuro (`marcar_analisis`). Los metadatos (nombre a mostrar, clase, versión,
quién) los guarda cada módulo en su tabla junto con la clave, el hash, el tipo y el tamaño de `Referencia`.
Si el registro en SQL falla, el módulo llama `eliminar(clave)` (compensación).
"""

import hashlib
import logging
import os
import uuid
from dataclasses import dataclass
from functools import lru_cache

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config.settings import get_settings
from app.core.database.mongo import coleccion
from app.core.documentos.almacen import (
    COLECCION,
    AlmacenDocumentos,
    AlmacenMongo,
    Analisis,
    DocumentoInexistente,
    ErrorAlmacen,
)
from app.core.documentos.analisis import analizar

logger = logging.getLogger(__name__)
_NONCE = 12

# Firma (primeros bytes) de cada tipo permitido
TIPOS_PERMITIDOS: dict[str, tuple[bytes, ...]] = {
    "application/pdf": (b"%PDF-",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/jpeg": (b"\xff\xd8\xff",),
}
EXTENSION = {"application/pdf": "pdf", "image/png": "png", "image/jpeg": "jpg"}


class ErrorDocumento(Exception):
    """Base. Los mensajes nunca llevan el contenido ni el nombre del archivo."""


class AlmacenamientoNoDisponible(ErrorDocumento):
    """Sin configuración (MONGO_URI, DOCUMENTOS_CLAVE) o MongoDB no responde: 503."""


class ArchivoMuyGrande(ErrorDocumento):
    """413."""


class TipoNoPermitido(ErrorDocumento):
    """415: el contenido no es PDF, JPG ni PNG (o no es del tipo que se exige)."""


class ArchivoRechazado(ErrorDocumento):
    """422: el análisis antimalware lo rechazó. `motivo` es un código corto para logs y
    auditoría (p. ej. "PDF_CONTENIDO_ACTIVO"); nunca va al usuario ni lleva contenido."""

    def __init__(self, motivo: str | None = None) -> None:
        super().__init__(motivo or "RECHAZADO")
        self.motivo = motivo


class DocumentoNoEncontrado(ErrorDocumento):
    """404."""


class DocumentoNoDisponible(ErrorDocumento):
    """El análisis está pendiente o lo rechazó: no se entrega (409)."""


@dataclass(frozen=True)
class Referencia:
    """Lo que el módulo guarda en su tabla para encontrar el documento."""

    clave: str
    sha256: str
    tamano: int
    tipo_contenido: str
    analisis: Analisis


@dataclass(frozen=True)
class Documento:
    contenido: bytes
    tipo_contenido: str


def tipo_por_contenido(contenido: bytes) -> str | None:
    """El tipo según los primeros bytes; None si no es uno permitido."""
    for tipo, firmas in TIPOS_PERMITIDOS.items():
        if any(contenido.startswith(f) for f in firmas):
            return tipo
    return None


@dataclass(frozen=True)
class ServicioDocumentos:
    almacen: AlmacenDocumentos
    clave_cifrado: bytes
    max_bytes: int

    def _dato_asociado(self, clave: str) -> bytes:
        return f"documento:{clave}".encode()

    def guardar(
        self,
        contenido: bytes,
        *,
        origen: str,
        generado_por_sistema: bool = False,
        tipos: tuple[str, ...] | None = None,
    ) -> Referencia:
        """Valida, cifra y guarda. `origen` dice qué módulo lo guardó (p. ej.
        "clientes", "creditos"); `tipos` restringe los permitidos (p. ej. solo PDF)."""
        if len(contenido) > self.max_bytes:
            raise ArchivoMuyGrande()
        tipo = tipo_por_contenido(contenido)
        if tipo is None or (tipos is not None and tipo not in tipos):
            raise TipoNoPermitido()
        if not generado_por_sistema:
            resultado = analizar(contenido, tipo)
            if resultado.veredicto == "Rechazado":
                logger.warning(
                    "documentos: archivo rechazado origen=%s motivo=%s",
                    origen,
                    resultado.motivo,
                )
                raise ArchivoRechazado(resultado.motivo)
        clave = uuid.uuid4().hex
        sha256 = hashlib.sha256(contenido).hexdigest()
        nonce = os.urandom(_NONCE)
        cifrado = nonce + AESGCM(self.clave_cifrado).encrypt(
            nonce, contenido, self._dato_asociado(clave)
        )
        analisis: Analisis = "Limpio"
        try:
            self.almacen.guardar(
                clave,
                cifrado,
                tipo_contenido=tipo,
                tamano=len(contenido),
                sha256=sha256,
                origen=origen,
                analisis=analisis,
            )
        except ErrorAlmacen as exc:
            logger.error("documentos: no se pudo guardar error=%s", exc)
            raise AlmacenamientoNoDisponible() from None
        return Referencia(clave, sha256, len(contenido), tipo, analisis)

    def leer(self, clave: str) -> Documento:
        """Solo documentos `Limpio`. Descifra y devuelve el contenido."""
        try:
            guardado = self.almacen.leer(clave)
        except DocumentoInexistente:
            raise DocumentoNoEncontrado() from None
        except ErrorAlmacen as exc:
            logger.error("documentos: no se pudo leer error=%s", exc)
            raise AlmacenamientoNoDisponible() from None
        if guardado.analisis != "Limpio":
            raise DocumentoNoDisponible()
        try:
            contenido = AESGCM(self.clave_cifrado).decrypt(
                guardado.contenido[:_NONCE],
                guardado.contenido[_NONCE:],
                self._dato_asociado(clave),
            )
        except InvalidTag:
            # Otra clave de cifrado o contenido de otro documento: nunca se entrega
            logger.error("documentos: no se pudo descifrar el documento")
            raise AlmacenamientoNoDisponible() from None
        return Documento(contenido, guardado.tipo_contenido)

    def eliminar(self, clave: str) -> None:
        """Compensación best-effort: si falla, queda huérfano para la limpieza."""
        try:
            self.almacen.eliminar(clave)
        except ErrorAlmacen as exc:
            logger.warning("documentos: no se pudo eliminar error=%s", exc)

    def marcar_analisis(self, clave: str, analisis: Analisis) -> None:
        """Para un análisis posterior (p. ej. reanalizar o un análisis asíncrono)."""
        try:
            self.almacen.marcar_analisis(clave, analisis)
        except DocumentoInexistente:
            raise DocumentoNoEncontrado() from None
        except ErrorAlmacen:
            raise AlmacenamientoNoDisponible() from None


@lru_cache
def _servicio_configurado(clave_hex: str, max_bytes: int) -> ServicioDocumentos | None:
    try:
        clave = bytes.fromhex(clave_hex)
    except ValueError:
        clave = b""
    if len(clave) != 32:
        if clave_hex:
            logger.warning("documentos: DOCUMENTOS_CLAVE no es AES-256 (64 hex)")
        return None
    destino = coleccion(COLECCION)
    if destino is None:
        return None
    return ServicioDocumentos(AlmacenMongo(destino), clave, max_bytes)


def obtener_servicio() -> ServicioDocumentos:
    """El servicio con MongoDB. AlmacenamientoNoDisponible (503) si falta MONGO_URI o
    DOCUMENTOS_CLAVE: el resto de la pantalla sigue funcionando."""
    s = get_settings()
    servicio = _servicio_configurado(
        s.documentos_clave.get_secret_value(), s.documentos_max_bytes
    )
    if servicio is None:
        raise AlmacenamientoNoDisponible()
    return servicio
