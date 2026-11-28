"""Identificación compartida del PAN mediante HMAC-SHA-256."""

from app.core.security.hsm import Hsm, obtener_hsm


def hash_pan(pan: str, hsm: Hsm | None = None) -> bytes:
    """Calcula la huella HMAC; no existe ruta SHA ni huella sin clave."""
    if not isinstance(pan, str):
        raise TypeError("PAN inválido")
    servicio = hsm if hsm is not None else obtener_hsm()
    return servicio.huella_pan(pan)
