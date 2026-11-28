import hmac

from app.core.security.hsm import Hsm
from app.modules.tarjetas.identificacion import hash_pan


def validar_hash_pan(
    pan: str,
    hash_almacenado: bytes | bytearray | memoryview | str,
    hsm: Hsm,
) -> bool:
    """Compara HMAC-SHA-256 del PAN con la huella almacenada."""

    if not isinstance(pan, str):
        return False

    if not pan.isascii() or not pan.isdigit():
        return False

    if isinstance(hash_almacenado, (bytes, bytearray, memoryview)):
        return hmac.compare_digest(hash_pan(pan, hsm), bytes(hash_almacenado))

    if not isinstance(hash_almacenado, str):
        return False

    hash_calculado = hash_pan(pan, hsm).hex()

    return hmac.compare_digest(
        hash_calculado.lower(),
        hash_almacenado.lower(),
    )
