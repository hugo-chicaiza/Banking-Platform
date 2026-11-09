import hmac

from app.modules.tarjetas.identificacion import hash_pan


def validar_hash_pan(
    pan: str,
    hash_almacenado: bytes | bytearray | memoryview | str,
) -> bool:
    """Compara el SHA-256 del PAN ficticio con el hash almacenado."""

    if not isinstance(pan, str):
        return False

    if not pan.isascii() or not pan.isdigit():
        return False

    if isinstance(hash_almacenado, (bytes, bytearray, memoryview)):
        return hmac.compare_digest(hash_pan(pan), bytes(hash_almacenado))

    if not isinstance(hash_almacenado, str):
        return False

    hash_calculado = hash_pan(pan).hex()

    return hmac.compare_digest(
        hash_calculado.lower(),
        hash_almacenado.lower(),
    )
