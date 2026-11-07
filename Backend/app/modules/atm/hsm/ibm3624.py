from cryptography.hazmat.decrepit.ciphers.algorithms import TripleDES
from cryptography.hazmat.primitives.ciphers import Cipher, modes

DECIMALIZATION_TABLE = "0123456789012345"


def calcular_pin_natural(
    validation_data: str,
    pin_generation_key: bytes,
    pin_length: int = 4,
) -> str:
    """Calcula el PIN natural IBM 3624 para un entorno de pruebas."""

    if len(pin_generation_key) not in (16, 24):
        raise ValueError("La clave de generación debe tener 16 o 24 bytes")

    if not 1 <= pin_length <= 16:
        raise ValueError("Longitud de PIN no válida")

    if len(validation_data) != 16:
        raise ValueError(
            "Los datos de validación deben tener 16 caracteres hexadecimales"
        )

    try:
        bloque = bytes.fromhex(validation_data)
    except ValueError as exc:
        raise ValueError("Datos de validación no válidos") from exc

    cipher = Cipher(
        TripleDES(pin_generation_key),
        modes.ECB(),
    )

    encryptor = cipher.encryptor()
    resultado = encryptor.update(bloque) + encryptor.finalize()

    hexadecimal = resultado.hex().upper()

    decimalizado = "".join(
        DECIMALIZATION_TABLE[int(caracter, 16)] for caracter in hexadecimal
    )

    return decimalizado[:pin_length]


def generar_offset(pin: str, pin_natural: str) -> str:
    """Calcula el Offset mediante resta decimal módulo 10."""

    if len(pin) != len(pin_natural):
        raise ValueError("Longitudes de PIN incompatibles")

    if not pin.isascii() or not pin.isdigit():
        raise ValueError("PIN no válido")

    if not pin_natural.isascii() or not pin_natural.isdigit():
        raise ValueError("PIN natural no válido")

    return "".join(str((int(a) - int(b)) % 10) for a, b in zip(pin, pin_natural))
