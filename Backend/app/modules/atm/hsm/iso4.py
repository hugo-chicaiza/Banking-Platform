from cryptography.hazmat.primitives.ciphers import (
    Cipher,
    algorithms,
    modes,
)


def aes_decrypt_block(block: bytes, key: bytes) -> bytes:
    """Descifra un bloque AES de 16 bytes."""

    if len(key) != 32:
        raise ValueError("AES-256 requiere una clave de 32 bytes")

    if len(block) != 16:
        raise ValueError("AES requiere un bloque de 16 bytes")

    # ISO 9564 formato 4 utiliza operaciones AES de bloque.
    # Excepción B305 limitada al simulador de laboratorio.
    # No utilizar como implementación HSM de producción.
    cipher = Cipher(
        algorithms.AES(key),
        modes.ECB(),  # nosec B305
    )

    decryptor = cipher.decryptor()

    return decryptor.update(block) + decryptor.finalize()


def construir_campo_pan(pan: str) -> bytes:
    """Construye el campo PAN de 16 bytes para ISO-4."""

    if not pan.isascii() or not pan.isdigit():
        raise ValueError("El PAN debe contener solo dígitos ASCII")

    if not 1 <= len(pan) <= 19:
        raise ValueError("Longitud de PAN no válida")

    longitud = max(len(pan), 12)
    indicador = longitud - 12

    campo_hex = (f"{indicador:X}" + pan.zfill(12)).ljust(32, "0")

    return bytes.fromhex(campo_hex)


def aplicar_xor(bloque_a: bytes, bloque_b: bytes) -> bytes:
    """Aplica XOR byte por byte."""

    if len(bloque_a) != 16 or len(bloque_b) != 16:
        raise ValueError("Ambos bloques deben tener 16 bytes")

    return bytes(a ^ b for a, b in zip(bloque_a, bloque_b))


def descifrar_pin_block_iso4(
    pin_block_cifrado: bytes,
    pan: str,
    clave: bytes,
) -> str:
    """Descifra un PIN Block ISO-4 en un simulador de laboratorio."""

    if len(pin_block_cifrado) != 16:
        raise ValueError("El PIN Block ISO-4 debe tener 16 bytes")

    # Primer descifrado AES.
    bloque_intermedio_b = aes_decrypt_block(
        pin_block_cifrado,
        clave,
    )

    # Construir el campo PAN.
    campo_pan = construir_campo_pan(pan)

    # Recuperar el bloque intermedio A mediante XOR.
    bloque_intermedio_a = aplicar_xor(
        bloque_intermedio_b,
        campo_pan,
    )

    # Segundo descifrado AES.
    campo_pin = aes_decrypt_block(
        bloque_intermedio_a,
        clave,
    )

    # Interpretar el campo PIN.
    campo_hex = campo_pin.hex().upper()

    if campo_hex[0] != "4":
        raise ValueError("Formato PIN Block inválido")

    longitud_pin = int(campo_hex[1], 16)

    if not 4 <= longitud_pin <= 12:
        raise ValueError("Longitud del PIN inválida")

    pin = campo_hex[2 : 2 + longitud_pin]

    if not pin.isascii() or not pin.isdigit():
        raise ValueError("El PIN contiene caracteres inválidos")

    relleno = campo_hex[2 + longitud_pin : 16]

    if relleno != "A" * (14 - longitud_pin):
        raise ValueError("Relleno ISO-4 inválido")

    return pin
