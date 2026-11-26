"""Análisis antimalware de archivos subidos (E5-08 #389): reglas locales + reputación.

Sin servicios pagos ni contenedores: reglas locales sobre la estructura del archivo y,
si hay `VIRUSTOTAL_API_KEY`, la reputación de su SHA-256 en VirusTotal.

- OWASP ASVS 5.0 V5 (5.2.1 tamaño lo controla el servicio; 5.2.2 el tipo se valida por
  contenido y estructura, no por extensión; 5.4.3 análisis antimalware de lo que sube
  un usuario antes de entregarlo).
- PDF: se rechaza el contenido activo o riesgoso (/JavaScript, /JS, /AA, /Launch,
  archivos embebidos, /RichMedia, /XFA, formularios que envían o importan datos, /GoToR,
  /URI javascript: o file:) aunque el nombre venga ofuscado con #xx, también dentro de
  flujos de objetos (/ObjStm). /OpenAction solo se acepta como destino ([pág /Fit…]),
  que es lo que emite fpdf2. Cifrado (/Encrypt) no se puede analizar: se rechaza. Sin
  %%EOF, mal formado.
- PNG/JPEG: se recorre la estructura hasta IEND/EOI; datos detrás (políglotas como
  PNG+ZIP) o firmas embebidas de ejecutables, ZIP o scripts se rechazan.
- Texto/CSV: UTF-8 estricto (con o sin BOM), sin NUL ni controles salvo tab/CR/LF, sin
  firmas binarias ni scripts.
- LOPDP Ecuador: a VirusTotal solo viaja el hash, nunca el archivo (datos personales
  como cédulas o estados de cuenta no salen a terceros). Si VirusTotal falla o tarda,
  no bloquea: queda el análisis local y un warning sin datos del archivo.

El `motivo` es un código corto para logs y auditoría; nunca lleva contenido del archivo.
"""

import hashlib
import logging
import re
import zlib
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Literal

import httpx

from app.core.config.settings import get_settings

logger = logging.getLogger(__name__)

Veredicto = Literal["Limpio", "Rechazado"]

# Firma de prueba estándar (eicar.org), partida para que el código fuente no la contenga
EICAR = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$" + b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
VIRUSTOTAL_URL = "https://www.virustotal.com/api/v3/files/{}"
VIRUSTOTAL_TIMEOUT = 3.0
TIPOS_TEXTO = frozenset({"text/csv", "text/plain"})

_PDF_PELIGROSOS = frozenset(
    {
        b"JavaScript",
        b"JS",
        b"AA",
        b"Launch",
        b"EmbeddedFile",
        b"EmbeddedFiles",
        b"RichMedia",
        b"XFA",
        b"SubmitForm",
        b"ImportData",
        b"GoToR",
    }
)
_URI_PELIGROSAS = (b"javascript:", b"file:")
_ESPACIOS = b"\x00\t\n\x0c\r "
_DELIMITADORES = _ESPACIOS + b"()<>[]{}/%"
_MAX_DESCOMPRIMIDO = 20 * 1024 * 1024  # contra bombas de descompresión en /ObjStm
_ESCAPES = {
    ord("n"): b"\n",
    ord("r"): b"\r",
    ord("t"): b"\t",
    ord("b"): b"\b",
    ord("f"): b"\f",
}

_FIRMAS_BINARIAS = (
    re.compile(rb"\x7fELF[\x01\x02][\x01\x02]\x01"),  # ejecutable Linux
    re.compile(rb"PK\x03\x04[\x0a-\x3f]\x00"),  # ZIP (también docx, jar, apk)
)
# Solo imágenes y texto: un navegador o intérprete podría ejecutarlos. En un PDF son
# texto inofensivo (p. ej. un título); su JavaScript real lo cubren /JS y /JavaScript.
_FIRMAS_SCRIPT = (
    re.compile(rb"#!\s?/(?:usr/)?bin/"),  # script con intérprete
    re.compile(rb"<script", re.IGNORECASE),
)
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_MAGIA = {
    "application/pdf": b"%PDF-",
    "image/png": b"\x89PNG\r\n\x1a\n",
    "image/jpeg": b"\xff\xd8\xff",
}


@dataclass(frozen=True)
class Resultado:
    veredicto: Veredicto
    motivo: str | None = None


LIMPIO = Resultado("Limpio")


def _rechazo(motivo: str) -> Resultado:
    return Resultado("Rechazado", motivo)


def _ejecutable_windows(datos: bytes) -> bool:
    """`MZ` con su cabecera PE (`PE\\0\\0` en e_lfanew): un .exe/.dll embebido."""
    for marca in re.finditer(rb"MZ", datos):
        inicio = marca.start()
        if inicio + 0x40 > len(datos):
            break
        desplazamiento = int.from_bytes(datos[inicio + 0x3C : inicio + 0x40], "little")
        if 0x40 <= desplazamiento <= 0x400:
            pe = inicio + desplazamiento
            if datos[pe : pe + 4] == b"PE\x00\x00":
                return True
    return False


def _firma_embebida(datos: bytes, scripts: bool) -> bool:
    firmas = _FIRMAS_BINARIAS + (_FIRMAS_SCRIPT if scripts else ())
    return (
        (scripts and datos.startswith(b"#!"))
        or _ejecutable_windows(datos)
        or any(firma.search(datos) for firma in firmas)
    )


# --- PDF -----------------------------------------------------------------------------


def _nombre(crudo: bytes) -> bytes:
    """Nombre PDF sin ofuscación: `/J#61vaScript` es `/JavaScript`."""
    return re.sub(rb"#([0-9A-Fa-f]{2})", lambda m: bytes([int(m.group(1), 16)]), crudo)


def _cadena_literal(datos: bytes, i: int) -> tuple[bytes, int]:
    """`( … )` con paréntesis anidados y escapes; devuelve (texto, fin)."""
    salida = bytearray()
    profundidad = 1
    j = i + 1
    while j < len(datos):
        b = datos[j]
        if b == 0x5C:  # barra invertida
            j += 1
            if j >= len(datos):
                break
            e = datos[j]
            octal = re.match(rb"[0-7]{1,3}", datos[j : j + 3])
            if octal:
                salida.append(int(octal.group(), 8) & 0xFF)
                j += len(octal.group())
                continue
            salida += _ESCAPES.get(e, bytes([e]))
        elif b == 0x28:
            profundidad += 1
            salida.append(b)
        elif b == 0x29:
            profundidad -= 1
            if profundidad == 0:
                return bytes(salida), j + 1
            salida.append(b)
        else:
            salida.append(b)
        j += 1
    return bytes(salida), len(datos)


def _tokens(datos: bytes) -> Iterator[tuple[str, bytes]]:
    """Fichas del PDF: ("n", nombre), ("s", cadena), ("k", palabra o delimitador) y
    ("flujo", contenido). Los flujos y cadenas no se confunden con nombres: un título
    "(/JS)" o texto comprimido no disparan reglas."""
    i, n = 0, len(datos)
    while i < n:
        c = datos[i]
        if c in _ESPACIOS:
            i += 1
        elif c == 0x25:  # % comentario
            while i < n and datos[i] not in b"\r\n":
                i += 1
        elif c == 0x28:
            texto, i = _cadena_literal(datos, i)
            yield "s", texto
        elif c == 0x3C and datos[i + 1 : i + 2] == b"<":
            yield "k", b"<<"
            i += 2
        elif c == 0x3C:
            fin = datos.find(b">", i)
            fin = n if fin < 0 else fin
            hexa = re.sub(rb"[^0-9A-Fa-f]", b"", datos[i + 1 : fin])
            yield "s", bytes.fromhex((hexa + b"0" * (len(hexa) % 2)).decode())
            i = fin + 1
        elif c == 0x3E:
            doble = datos[i + 1 : i + 2] == b">"
            yield "k", b">>" if doble else b">"
            i += 2 if doble else 1
        elif c in b"[]{}":
            yield "k", bytes([c])
            i += 1
        elif c == 0x2F:
            j = i + 1
            while j < n and datos[j] not in _DELIMITADORES:
                j += 1
            yield "n", _nombre(datos[i + 1 : j])
            i = j
        else:
            j = i
            while j < n and datos[j] not in _DELIMITADORES:
                j += 1
            palabra = datos[i:j]
            i = j
            if palabra != b"stream":
                yield "k", palabra
                continue
            if datos[i : i + 2] == b"\r\n":
                i += 2
            elif datos[i : i + 1] in (b"\n", b"\r"):
                i += 1
            fin = datos.find(b"endstream", i)
            fin = n if fin < 0 else fin
            yield "flujo", datos[i:fin]
            i = fin + len(b"endstream")


def _uri_peligrosa(valor: bytes) -> bool:
    limpio = bytes(b for b in valor if b > 0x20).lower()
    return limpio.startswith(_URI_PELIGROSAS)


def _revisar_pdf(datos: bytes, anidado: bool = False) -> str | None:
    objstm = flate = False
    esperando: bytes | None = None
    for clase, valor in _tokens(datos):
        if esperando == b"OpenAction" and valor != b"[":
            return "PDF_CONTENIDO_ACTIVO"  # una acción, no un destino de página
        if esperando == b"URI" and clase == "s" and _uri_peligrosa(valor):
            return "PDF_URI_PELIGROSA"
        esperando = None
        if clase == "n":
            if valor in _PDF_PELIGROSOS:
                return "PDF_CONTENIDO_ACTIVO"
            if valor == b"Encrypt":
                return "PDF_CIFRADO"
            if valor in (b"OpenAction", b"URI"):
                esperando = valor
            objstm = objstm or valor == b"ObjStm"
            flate = flate or valor == b"FlateDecode"
        elif clase == "k" and valor in (b"obj", b"endobj"):
            objstm = flate = False
        elif clase == "flujo" and objstm and not anidado:
            # Los diccionarios pueden esconderse comprimidos dentro de /ObjStm
            contenido = valor
            if flate:
                descompresor = zlib.decompressobj()
                try:
                    contenido = descompresor.decompress(valor, _MAX_DESCOMPRIMIDO)
                except zlib.error:
                    return "PDF_MAL_FORMADO"
                if descompresor.unconsumed_tail:
                    return "PDF_NO_ANALIZABLE"
            motivo = _revisar_pdf(contenido, anidado=True)
            if motivo:
                return motivo
    if esperando == b"OpenAction":
        return "PDF_CONTENIDO_ACTIVO"
    return None


def _analizar_pdf(datos: bytes) -> str | None:
    if b"%%EOF" not in datos[-1024:]:
        return "PDF_SIN_FIN"
    return _revisar_pdf(datos)


# --- Imágenes ------------------------------------------------------------------------


def _fin_png(datos: bytes) -> int | None:
    """Posición tras el bloque IEND; None si la estructura está rota."""
    i = 8
    while i + 12 <= len(datos):
        largo = int.from_bytes(datos[i : i + 4], "big")
        tipo = datos[i + 4 : i + 8]
        i += 12 + largo
        if i > len(datos):
            return None
        if tipo == b"IEND":
            return i
    return None


def _fin_jpeg(datos: bytes) -> int | None:
    """Posición tras el marcador EOI (FFD9) recorriendo segmentos y datos de imagen;
    una miniatura EXIF con su propio FFD9 no engaña porque va dentro de su segmento."""
    i, n = 2, len(datos)
    while i + 2 <= n:
        if datos[i] != 0xFF:
            return None
        marcador = datos[i + 1]
        if marcador == 0xFF:  # relleno
            i += 1
            continue
        if marcador == 0xD9:
            return i + 2
        if 0xD0 <= marcador <= 0xD7 or marcador == 0x01:
            i += 2
            continue
        if i + 4 > n:
            return None
        largo = int.from_bytes(datos[i + 2 : i + 4], "big")
        if largo < 2 or i + 2 + largo > n:
            return None
        i += 2 + largo
        if marcador != 0xDA:
            continue
        while True:  # datos comprimidos hasta el siguiente marcador
            j = datos.find(b"\xff", i)
            if j < 0 or j + 1 >= n:
                return None
            siguiente = datos[j + 1]
            if siguiente == 0x00 or 0xD0 <= siguiente <= 0xD7:
                i = j + 2
                continue
            i = j
            break
    return None


def _analizar_imagen(datos: bytes, tipo: str) -> str | None:
    fin = _fin_png(datos) if tipo == "image/png" else _fin_jpeg(datos)
    if fin is None:
        return "IMAGEN_MAL_FORMADA"
    if datos[fin:].strip(b"\x00\xff" if tipo == "image/jpeg" else b""):
        return "DATOS_TRAS_FIN"
    return None


# --- Texto ---------------------------------------------------------------------------


def _analizar_texto(datos: bytes) -> str | None:
    cuerpo = datos.removeprefix(b"\xef\xbb\xbf")
    try:
        texto = cuerpo.decode("utf-8")
    except UnicodeDecodeError:
        return "TEXTO_NO_UTF8"
    if _CONTROL.search(texto):
        return "TEXTO_CON_CONTROL"
    if cuerpo.startswith(tuple(_MAGIA.values())):
        return "FIRMA_EMBEBIDA"
    return None


# --- Reputación ----------------------------------------------------------------------


def _clave_reputacion() -> str:
    return get_settings().virustotal_api_key.get_secret_value()


def _reputacion(sha256: str, clave: str) -> str | None:
    """Solo el hash viaja (LOPDP). 404 = sin antecedentes; un fallo no bloquea."""
    try:
        respuesta = httpx.get(
            VIRUSTOTAL_URL.format(sha256),
            headers={"x-apikey": clave, "accept": "application/json"},
            timeout=VIRUSTOTAL_TIMEOUT,
        )
    except httpx.HTTPError as exc:
        logger.warning(
            "analisis: reputación no disponible error=%s", type(exc).__name__
        )
        return None
    if respuesta.status_code == 404:
        return None
    if respuesta.status_code != 200:
        logger.warning(
            "analisis: reputación no disponible status=%s", respuesta.status_code
        )
        return None
    try:
        estadisticas = respuesta.json()["data"]["attributes"]["last_analysis_stats"]
        maliciosos = int(estadisticas["malicious"])
    except (ValueError, KeyError, TypeError):
        logger.warning("analisis: reputación con formato inesperado")
        return None
    return "REPUTACION_MALICIOSA" if maliciosos > 0 else None


def analizar(contenido: bytes, tipo: str) -> Resultado:
    """Veredicto de un archivo de `tipo` (el detectado por contenido, no el declarado).
    Un tipo sin reglas se rechaza (falla cerrado)."""
    if EICAR in contenido:
        return _rechazo("EICAR")
    if tipo in TIPOS_TEXTO:
        motivo = _analizar_texto(contenido)
    elif tipo in _MAGIA:
        if not contenido.startswith(_MAGIA[tipo]):
            return _rechazo("TIPO_NO_COINCIDE")
        motivo = (
            _analizar_pdf(contenido)
            if tipo == "application/pdf"
            else _analizar_imagen(contenido, tipo)
        )
    else:
        return _rechazo("TIPO_NO_ANALIZABLE")
    if motivo is None and _firma_embebida(contenido, tipo != "application/pdf"):
        motivo = "FIRMA_EMBEBIDA"
    if motivo:
        return _rechazo(motivo)
    clave = _clave_reputacion()
    if clave:
        motivo = _reputacion(hashlib.sha256(contenido).hexdigest(), clave)
        if motivo:
            return _rechazo(motivo)
    return LIMPIO
