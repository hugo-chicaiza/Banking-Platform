import hashlib
import hmac


def validar_hash_pan(
    pan: str,
    hash_almacenado: str,
) -> bool:
    """Compara el SHA-256 del PAN ficticio con el hash almacenado."""

    if not isinstance(pan, str):
        return False

    if not pan.isascii() or not pan.isdigit():
        return False

    if not isinstance(hash_almacenado, str):
        return False

    hash_calculado = hashlib.sha256(pan.encode("ascii")).hexdigest()

    return hmac.compare_digest(
        hash_calculado.lower(),
        hash_almacenado.lower(),
    )
