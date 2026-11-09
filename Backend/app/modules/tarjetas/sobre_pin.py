"""Sobre de PIN de débito (TAR-04, TAR-05 y TAR-07).

Al aprobar una tarjeta de débito, o al regenerar su PIN, el HSM entrega el PIN temporal
solo para imprimir el sobre (como la salida "PIN mailer" de un HSM de pagos). Aquí se
arma el PDF que se entrega al cliente con la tarjeta, se cifra (AES-256-GCM) y se guarda
para descargarse UNA sola vez (TAR-07). Al entregarse se borra el contenido.

Almacén:
- MongoDB (colección `sobres_pin`) si hay MONGO_URI. Al crear la base en Azure solo se
  configura MONGO_URI: el código no cambia.
- Mientras no exista, fuera de producción, una carpeta local (SOBRE_PIN_DIR).
- Sin almacén o sin SOBRE_PIN_CLAVE no hay sobres: `obtener_servicio()` devuelve None.

El PIN y el PDF nunca se registran en logs ni en la auditoría.
"""

import base64
import json
import logging
import os
import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, Protocol

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fpdf import FPDF
from fpdf.enums import XPos, YPos
from pydantic import SecretStr

from app.core.config.settings import get_settings

logger = logging.getLogger(__name__)

OrigenSobre = Literal["Aprobacion", "Regeneracion"]

COLECCION = "sobres_pin"
_NONCE_GCM = 12
_TIMEOUT_MONGO_MS = 5000


class ErrorSobre(Exception):
    """Base de los errores del sobre de PIN. Los mensajes no llevan datos sensibles."""


class SobreNoDisponible(ErrorSobre):
    """No hay sobre pendiente y vigente (crédito, vencido, nunca generado)."""


class SobreYaEntregado(ErrorSobre):
    """El sobre ya se descargó: para otra hoja hay que regenerar el PIN (TAR-05)."""


class AlmacenNoDisponible(ErrorSobre):
    """El almacén no responde o el contenido no se puede descifrar."""


# --- PDF -------------------------------------------------------------------------


def construir_pdf(pin: SecretStr, cooperativa: str, sitio_web: str) -> bytes:
    """Una página A4: bienvenida, sitio web, indicación de cambio y el PIN centrado al
    final. Sin número de tarjeta ni datos del cliente.
    """
    pdf = FPDF(format="A4")
    pdf.set_title("Sobre de PIN")
    pdf.set_creator(cooperativa)
    pdf.set_margins(25, 30, 25)
    pdf.set_auto_page_break(auto=False)
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 22)
    pdf.multi_cell(0, 12, f"Bienvenido a la Cooperativa {cooperativa}", align="C")
    pdf.ln(10)

    pdf.set_font("Helvetica", "", 13)
    pdf.multi_cell(
        0,
        8,
        f"Para conocer los beneficios de tu tarjeta ingresa a {sitio_web}",
        align="C",
    )
    pdf.ln(8)
    pdf.set_font("Helvetica", "", 11)
    pdf.multi_cell(
        0,
        7,
        "Este es tu PIN temporal. Antes de usar tu tarjeta, cámbialo en cualquier "
        "cajero automático de la cooperativa. No lo compartas con nadie: ningún "
        "funcionario de la cooperativa te lo pedirá.",
        align="C",
    )

    # El PIN, centrado al final de la hoja
    pdf.set_y(-90)
    pdf.set_font("Helvetica", "", 12)
    pdf.cell(0, 8, "Tu PIN", align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Courier", "B", 40)
    pdf.cell(
        0,
        20,
        " ".join(pin.get_secret_value()),
        align="C",
        new_x=XPos.LMARGIN,
        new_y=YPos.NEXT,
    )
    return bytes(pdf.output())


# --- Cifrado ---------------------------------------------------------------------


@dataclass(frozen=True)
class Cifrador:
    """AES-256-GCM; el dato asociado liga el contenido a su tarjeta y a su sobre."""

    clave: bytes

    @staticmethod
    def _dato_asociado(id_tarjeta: int, id_sobre: str) -> bytes:
        return f"sobre-pin:{id_tarjeta}:{id_sobre}".encode()

    def cifrar(self, id_tarjeta: int, id_sobre: str, contenido: bytes) -> bytes:
        nonce = os.urandom(_NONCE_GCM)
        return nonce + AESGCM(self.clave).encrypt(
            nonce, contenido, self._dato_asociado(id_tarjeta, id_sobre)
        )

    def descifrar(self, id_tarjeta: int, id_sobre: str, cifrado: bytes) -> bytes:
        try:
            return AESGCM(self.clave).decrypt(
                cifrado[:_NONCE_GCM],
                cifrado[_NONCE_GCM:],
                self._dato_asociado(id_tarjeta, id_sobre),
            )
        except InvalidTag:
            # Otra clave o el contenido de otra tarjeta: nunca se entrega
            raise AlmacenNoDisponible("No se pudo descifrar el sobre") from None


# --- Almacenes -------------------------------------------------------------------


@dataclass(frozen=True)
class SobreEntregado:
    id_sobre: str
    contenido: bytes


class Almacen(Protocol):
    def guardar(
        self,
        id_tarjeta: int,
        id_sobre: str,
        contenido: bytes,
        origen: OrigenSobre,
        ahora: datetime,
        expira: datetime,
    ) -> None:
        """Guarda el sobre Pendiente y reemplaza el anterior de la tarjeta."""
        ...

    def entregar(
        self, id_tarjeta: int, usuario: int, ahora: datetime
    ) -> SobreEntregado:
        """Toma el sobre Pendiente y vigente y lo marca Entregado sin contenido, en una
        sola operación. SobreYaEntregado o SobreNoDisponible si no se puede.
        """
        ...

    def descartar(self, id_tarjeta: int, id_sobre: str) -> None:
        """Borra el sobre solo si sigue siendo `id_sobre` (compensación)."""
        ...


def _documento(
    id_sobre: str,
    contenido: bytes,
    origen: OrigenSobre,
    ahora: datetime,
    expira: datetime,
) -> dict[str, Any]:
    return {
        "idSobre": id_sobre,
        "estado": "Pendiente",
        "origen": origen,
        "contenido": contenido,
        "creadoEn": ahora,
        "expiraEn": expira,
    }


class AlmacenMongo:
    """Colección `sobres_pin`, un documento por tarjeta (`_id = idTarjeta`).

    El índice TTL sobre `expiraEn` borra los sobres vencidos; como Cosmos DB no siempre
    lo aplica, `entregar` además descarta los vencidos al leer.
    """

    def __init__(self, coleccion: Any) -> None:
        self._coleccion = coleccion
        self._indices_creados = False

    def _asegurar_indices(self) -> None:
        from pymongo.errors import PyMongoError

        if self._indices_creados:
            return
        try:
            self._coleccion.create_index("expiraEn", expireAfterSeconds=0)
        except PyMongoError as exc:  # el TTL es una ayuda, no un requisito
            logger.warning(
                "sobre_pin: no se pudo crear el índice TTL error=%s",
                type(exc).__name__,
            )
        self._indices_creados = True

    def guardar(
        self,
        id_tarjeta: int,
        id_sobre: str,
        contenido: bytes,
        origen: OrigenSobre,
        ahora: datetime,
        expira: datetime,
    ) -> None:
        from pymongo.errors import PyMongoError

        try:
            self._asegurar_indices()
            self._coleccion.replace_one(
                {"_id": id_tarjeta},
                {
                    "_id": id_tarjeta,
                    **_documento(id_sobre, contenido, origen, ahora, expira),
                },
                upsert=True,
            )
        except PyMongoError as exc:
            raise AlmacenNoDisponible(type(exc).__name__) from None

    def entregar(
        self, id_tarjeta: int, usuario: int, ahora: datetime
    ) -> SobreEntregado:
        from pymongo import ReturnDocument
        from pymongo.errors import PyMongoError

        try:
            previo = self._coleccion.find_one_and_update(
                {"_id": id_tarjeta, "estado": "Pendiente", "expiraEn": {"$gt": ahora}},
                {
                    "$set": {
                        "estado": "Entregado",
                        "entregadoEn": ahora,
                        "entregadoPor": usuario,
                    },
                    "$unset": {"contenido": "", "expiraEn": ""},
                },
                return_document=ReturnDocument.BEFORE,
            )
            if previo is not None:
                return SobreEntregado(previo["idSobre"], bytes(previo["contenido"]))
            actual = self._coleccion.find_one({"_id": id_tarjeta}, {"estado": 1})
            if actual is not None and actual.get("estado") == "Entregado":
                raise SobreYaEntregado()
            if actual is not None:
                # Pendiente pero vencido: se borra aunque el TTL no haya corrido
                self._coleccion.delete_one({"_id": id_tarjeta, "estado": "Pendiente"})
        except PyMongoError as exc:
            raise AlmacenNoDisponible(type(exc).__name__) from None
        raise SobreNoDisponible()

    def descartar(self, id_tarjeta: int, id_sobre: str) -> None:
        from pymongo.errors import PyMongoError

        try:
            self._coleccion.delete_one({"_id": id_tarjeta, "idSobre": id_sobre})
        except PyMongoError as exc:
            raise AlmacenNoDisponible(type(exc).__name__) from None


class AlmacenDisco:
    """Mientras no hay MongoDB, solo fuera de producción.

    `{id}.json` guarda el sobre Pendiente con el contenido ya cifrado. Al entregarse se
    borra y queda `{id}.entregado` con quién y cuándo, armado solo con datos de la
    petición (nunca se reescribe lo leído del archivo). Un candado de proceso hace
    atómica la entrega (un servidor de desarrollo).
    """

    _candado = threading.Lock()

    def __init__(self, carpeta: Path) -> None:
        self._carpeta = carpeta

    def _ruta(self, id_tarjeta: int, extension: str = ".json") -> Path:
        """Archivo de la tarjeta, siempre dentro de la carpeta de sobres: el nombre
        sale solo de un entero positivo y la ruta resuelta se verifica.
        """
        if (
            not isinstance(id_tarjeta, int)
            or isinstance(id_tarjeta, bool)
            or id_tarjeta <= 0
        ):
            raise AlmacenNoDisponible("Id de tarjeta inválido")
        carpeta = os.path.realpath(self._carpeta)
        ruta = os.path.realpath(os.path.join(carpeta, f"{id_tarjeta:d}{extension}"))
        if os.path.commonpath([carpeta, ruta]) != carpeta:
            raise AlmacenNoDisponible("Ruta fuera de la carpeta de sobres")
        return Path(ruta)

    def _leer(self, id_tarjeta: int) -> dict[str, Any] | None:
        ruta = self._ruta(id_tarjeta)
        if not ruta.exists():
            return None
        return json.loads(ruta.read_text(encoding="utf-8"))

    def _escribir(self, id_tarjeta: int, extension: str, texto: str) -> None:
        self._carpeta.mkdir(parents=True, exist_ok=True)
        temporal = self._ruta(id_tarjeta, ".tmp")
        temporal.write_text(texto, encoding="utf-8")
        os.replace(temporal, self._ruta(id_tarjeta, extension))

    def guardar(
        self,
        id_tarjeta: int,
        id_sobre: str,
        contenido: bytes,
        origen: OrigenSobre,
        ahora: datetime,
        expira: datetime,
    ) -> None:
        documento = _documento(id_sobre, contenido, origen, ahora, expira)
        documento["contenido"] = base64.b64encode(contenido).decode()
        documento["creadoEn"] = ahora.isoformat()
        documento["expiraEn"] = expira.isoformat()
        try:
            with self._candado:
                self._escribir(id_tarjeta, ".json", json.dumps(documento))
                self._ruta(id_tarjeta, ".entregado").unlink(missing_ok=True)
        except OSError as exc:
            raise AlmacenNoDisponible(type(exc).__name__) from None

    def entregar(
        self, id_tarjeta: int, usuario: int, ahora: datetime
    ) -> SobreEntregado:
        try:
            with self._candado:
                documento = self._leer(id_tarjeta)
                if documento is None:
                    if self._ruta(id_tarjeta, ".entregado").exists():
                        raise SobreYaEntregado()
                    raise SobreNoDisponible()
                if datetime.fromisoformat(documento["expiraEn"]) <= ahora:
                    self._ruta(id_tarjeta).unlink(missing_ok=True)
                    raise SobreNoDisponible()
                entregado = SobreEntregado(
                    str(documento["idSobre"]), base64.b64decode(documento["contenido"])
                )
                entrega = {"entregadoEn": ahora.isoformat(), "entregadoPor": usuario}
                self._escribir(id_tarjeta, ".entregado", json.dumps(entrega))
                self._ruta(id_tarjeta).unlink()
        except (OSError, ValueError, KeyError) as exc:
            raise AlmacenNoDisponible(type(exc).__name__) from None
        return entregado

    def descartar(self, id_tarjeta: int, id_sobre: str) -> None:
        try:
            with self._candado:
                documento = self._leer(id_tarjeta)
                if documento is not None and documento.get("idSobre") == id_sobre:
                    self._ruta(id_tarjeta).unlink(missing_ok=True)
        except (OSError, ValueError) as exc:
            raise AlmacenNoDisponible(type(exc).__name__) from None


# --- Servicio --------------------------------------------------------------------


@dataclass(frozen=True)
class ServicioSobres:
    almacen: Almacen
    cifrador: Cifrador
    cooperativa: str
    sitio_web: str
    dias: int

    def preparar(self, id_tarjeta: int, pin: SecretStr, origen: OrigenSobre) -> str:
        """Arma, cifra y guarda el sobre; devuelve su id (para descartarlo si la
        operación que lo originó falla). AlmacenNoDisponible si no se pudo guardar.
        """
        id_sobre = uuid.uuid4().hex
        pdf = construir_pdf(pin, self.cooperativa, self.sitio_web)
        try:
            cifrado = self.cifrador.cifrar(id_tarjeta, id_sobre, pdf)
        finally:
            del pdf
        ahora = datetime.now(UTC)
        self.almacen.guardar(
            id_tarjeta,
            id_sobre,
            cifrado,
            origen,
            ahora,
            ahora + timedelta(days=self.dias),
        )
        return id_sobre

    def descartar(self, id_tarjeta: int, id_sobre: str) -> None:
        """Compensación best-effort: si falla, el sobre igual vence por TTL."""
        try:
            self.almacen.descartar(id_tarjeta, id_sobre)
        except AlmacenNoDisponible:
            logger.warning(
                "sobre_pin: no se pudo descartar el sobre id_tarjeta=%s", id_tarjeta
            )

    def entregar(self, id_tarjeta: int, usuario: int) -> bytes:
        sobre = self.almacen.entregar(id_tarjeta, usuario, datetime.now(UTC))
        return self.cifrador.descifrar(id_tarjeta, sobre.id_sobre, sobre.contenido)


@lru_cache
def _coleccion_mongo(uri: str, base: str) -> Any:
    from pymongo import MongoClient

    cliente: Any = MongoClient(
        uri, serverSelectionTimeoutMS=_TIMEOUT_MONGO_MS, tz_aware=True
    )
    return cliente[base][COLECCION]


def obtener_servicio() -> ServicioSobres | None:
    """None si no se pueden generar sobres: sin SOBRE_PIN_CLAVE, o en producción sin
    MONGO_URI. Nunca conecta a MongoDB sin MONGO_URI.
    """
    s = get_settings()
    clave_hex = s.sobre_pin_clave.get_secret_value()
    try:
        clave = bytes.fromhex(clave_hex)
    except ValueError:
        clave = b""
    if len(clave) != 32:
        if clave_hex:
            logger.warning("sobre_pin: SOBRE_PIN_CLAVE no es AES-256 (64 hex)")
        return None

    uri = s.mongo_uri.get_secret_value()
    almacen: Almacen
    if uri:
        almacen = AlmacenMongo(_coleccion_mongo(uri, s.mongo_db))
    elif s.app_env != "production":
        almacen = AlmacenDisco(Path(s.sobre_pin_dir))
    else:
        return None
    return ServicioSobres(
        almacen=almacen,
        cifrador=Cifrador(clave),
        cooperativa=s.cooperativa_nombre,
        sitio_web=s.cooperativa_sitio_web,
        dias=s.sobre_pin_dias,
    )
