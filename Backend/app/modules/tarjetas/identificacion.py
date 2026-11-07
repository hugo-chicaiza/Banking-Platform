"""Identificación compartida del PAN, con la representación binaria de TAR-01."""

import hashlib


def hash_pan(pan: str) -> bytes:
    """Calcula el mismo SHA-256 binario usado en la emisión; no conserva el PAN.

    La validación del formato pertenece al componente que recibe la entrada.
    """
    return hashlib.sha256(pan.encode()).digest()
