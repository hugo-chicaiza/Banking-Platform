import pytest
from cryptography.hazmat.primitives.ciphers import (
    Cipher,
    algorithms,
    modes,
)

from app.modules.atm.hsm.ibm3624 import (
    calcular_pin_natural,
    generar_offset,
)
from app.modules.atm.hsm.interface import PinVerificationRequest
from app.modules.atm.hsm.iso4 import (
    aplicar_xor,
    construir_campo_pan,
    descifrar_pin_block_iso4,
)
from app.modules.atm.hsm.simulator import SimulatedHsm


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_campo_pan():
    pan = "432198765432109870"

    resultado = construir_campo_pan(pan)

    assert resultado.hex().upper() == ("64321987654321098700000000000000")


def test_xor_reversible():
    a = bytes.fromhex("AA" * 16)
    b = bytes.fromhex("55" * 16)

    resultado = aplicar_xor(a, b)

    assert aplicar_xor(resultado, b) == a


def test_rechazar_bloque_invalido():
    with pytest.raises(ValueError):
        descifrar_pin_block_iso4(
            pin_block_cifrado=b"\x00" * 8,
            pan="432198765432109870",
            clave=bytes(range(32)),
        )


def test_descifrado_iso4_aes256():
    # Datos ficticios de laboratorio.
    clave = bytes(range(32))
    pan = "432198765432109870"

    # Campo PIN ISO-4 conocido.
    campo_pin = bytes.fromhex("441234AAAAAAAAAA911B9B36BC7CE94E")

    def cifrar_aes(bloque: bytes) -> bytes:
        cipher = Cipher(
            algorithms.AES(clave),
            modes.ECB(),
        )
        encryptor = cipher.encryptor()
        return encryptor.update(bloque) + encryptor.finalize()

    # Construir un PIN Block cifrado ISO-4.
    bloque_a = cifrar_aes(campo_pin)
    campo_pan = construir_campo_pan(pan)
    bloque_b = aplicar_xor(bloque_a, campo_pan)
    pin_block_cifrado = cifrar_aes(bloque_b)

    pin_recuperado = descifrar_pin_block_iso4(
        pin_block_cifrado=pin_block_cifrado,
        pan=pan,
        clave=clave,
    )

    assert pin_recuperado == "1234"


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("pin_ingresado", "esperado"),
    [
        ("1234", True),
        ("9999", False),
    ],
)
async def test_verificar_pin(pin_ingresado, esperado):
    clave = bytes(range(32))
    clave_ibm = bytes(range(24))
    pan = "432198765432109870"
    validation_data = "4321987654321098"

    campo_pin = bytes.fromhex(
        f"4{len(pin_ingresado):X}"
        f"{pin_ingresado}"
        f"{'A' * (14 - len(pin_ingresado))}"
        "911B9B36BC7CE94E"
    )

    def cifrar(bloque: bytes) -> bytes:
        cipher = Cipher(
            algorithms.AES(clave),
            modes.ECB(),
        )
        encryptor = cipher.encryptor()
        return encryptor.update(bloque) + encryptor.finalize()

    bloque_a = cifrar(campo_pin)

    bloque_b = aplicar_xor(
        bloque_a,
        construir_campo_pan(pan),
    )

    pin_block = cifrar(bloque_b)

    hsm = SimulatedHsm(
        test_key=clave,
        pin_generation_key=clave_ibm,
    )

    # Simula el Offset registrado previamente por TAR-05.
    pin_natural = calcular_pin_natural(
        validation_data=validation_data,
        pin_generation_key=clave_ibm,
        pin_length=4,
    )

    pin_offset = generar_offset(
        "1234",
        pin_natural,
    )

    solicitud = PinVerificationRequest(
        encrypted_pin_block=pin_block,
        pan=pan,
        key_reference="TEST-KEY-01",
        validation_data=validation_data,
        pin_offset=pin_offset,
    )

    resultado = await hsm.verify_pin(solicitud)

    assert resultado is esperado
