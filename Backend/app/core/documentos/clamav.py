"""Análisis ClamAV en una conexión privada al proceso clamd."""

import socket
import time

from app.core.config.settings import get_settings
from app.core.documentos.servicio import ArchivoRechazado, ErrorDocumento

_TIEMPO_MAXIMO = 10.0
_TAMANO_RESPUESTA = 1024


class AnalisisNoDisponible(ErrorDocumento):
    """El antivirus no confirmó un veredicto; se puede reintentar."""


def analizar_clamav(contenido: bytes) -> None:
    ajustes = get_settings()
    if not ajustes.documentos_clamav_host:
        raise AnalisisNoDisponible()

    fin = time.monotonic() + _TIEMPO_MAXIMO
    respuesta = bytearray()
    try:
        with socket.create_connection(
            (ajustes.documentos_clamav_host, ajustes.documentos_clamav_port),
            timeout=_TIEMPO_MAXIMO,
        ) as canal:
            canal.settimeout(max(0.001, fin - time.monotonic()))
            canal.sendall(b"zINSTREAM\0" + len(contenido).to_bytes(4, "big"))
            canal.settimeout(max(0.001, fin - time.monotonic()))
            canal.sendall(contenido)
            canal.settimeout(max(0.001, fin - time.monotonic()))
            canal.sendall(b"\0\0\0\0")
            while len(respuesta) < _TAMANO_RESPUESTA and b"\0" not in respuesta:
                restante = fin - time.monotonic()
                if restante <= 0:
                    raise AnalisisNoDisponible()
                canal.settimeout(restante)
                fragmento = canal.recv(_TAMANO_RESPUESTA - len(respuesta))
                if not fragmento:
                    break
                respuesta.extend(fragmento)
    except OSError:
        raise AnalisisNoDisponible() from None

    if respuesta == b"stream: OK\0":
        return
    if respuesta.startswith(b"stream: ") and respuesta.endswith(b" FOUND\0"):
        raise ArchivoRechazado("CLAMAV")
    raise AnalisisNoDisponible()
