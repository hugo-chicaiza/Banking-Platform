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
from app.modules.atm.hsm.interface import (
    PinGenerationRequest,
    PinVerificationRequest,
)
from app.modules.atm.hsm.iso4 import (
    aplicar_xor,
    construir_campo_pan,
)
from app.modules.atm.hsm.simulator import SimulatedHsm


@pytest.fixture
def anyio_backend():
    return "asyncio"


CLAVE_AES = bytes(range(32))
CLAVE_IBM = bytes(range(24))
PAN = "432198765432109870"
VALIDATION_DATA = "4321987654321098"


def crear_pin_block(pin: str) -> bytes:
    """Construye un PIN Block ISO-4 ficticio para pruebas."""

    campo_pin = bytes.fromhex(
        f"4{len(pin):X}{pin}{'A' * (14 - len(pin))}911B9B36BC7CE94E"
    )

    def cifrar(bloque: bytes) -> bytes:
        cipher = Cipher(
            algorithms.AES(CLAVE_AES),
            modes.ECB(),
        )
        encryptor = cipher.encryptor()
        return encryptor.update(bloque) + encryptor.finalize()

    bloque_a = cifrar(campo_pin)
    bloque_b = aplicar_xor(
        bloque_a,
        construir_campo_pan(PAN),
    )

    return cifrar(bloque_b)


def crear_hsm() -> SimulatedHsm:
    return SimulatedHsm(
        test_key=CLAVE_AES,
        pin_generation_key=CLAVE_IBM,
    )


def test_generar_offset():
    assert generar_offset("1234", "9876") == "2468"


def test_rechazar_pin_no_numerico():
    with pytest.raises(ValueError):
        generar_offset("12AB", "9876")


def test_pin_natural_determinista():
    primero = calcular_pin_natural(
        VALIDATION_DATA,
        CLAVE_IBM,
    )
    segundo = calcular_pin_natural(
        VALIDATION_DATA,
        CLAVE_IBM,
    )

    assert primero == segundo
    assert len(primero) == 4
    assert primero.isdigit()


@pytest.mark.anyio
async def test_flujo_asignacion_y_verificacion():
    hsm = crear_hsm()

    # TAR-05: asignación de PIN.
    offset = await hsm.generate_pin_offset(
        PinGenerationRequest(
            encrypted_pin_block=crear_pin_block("1234"),
            pan=PAN,
            key_reference="TEST-KEY-01",
            validation_data=VALIDATION_DATA,
        )
    )

    assert len(offset) == 4
    assert offset.isdigit()

    # ATM-01: autenticación con PIN correcto.
    correcto = await hsm.verify_pin(
        PinVerificationRequest(
            encrypted_pin_block=crear_pin_block("1234"),
            pan=PAN,
            key_reference="TEST-KEY-01",
            validation_data=VALIDATION_DATA,
            pin_offset=offset,
        )
    )

    # ATM-01: autenticación con PIN incorrecto.
    incorrecto = await hsm.verify_pin(
        PinVerificationRequest(
            encrypted_pin_block=crear_pin_block("9999"),
            pan=PAN,
            key_reference="TEST-KEY-01",
            validation_data=VALIDATION_DATA,
            pin_offset=offset,
        )
    )

    assert correcto is True
    assert incorrecto is False


@pytest.mark.anyio
async def test_rechazar_referencia_clave_desconocida():
    hsm = crear_hsm()

    with pytest.raises(ValueError, match="Referencia de clave desconocida"):
        await hsm.generate_pin_offset(
            PinGenerationRequest(
                encrypted_pin_block=crear_pin_block("1234"),
                pan=PAN,
                key_reference="CLAVE-NO-AUTORIZADA",
                validation_data=VALIDATION_DATA,
            )
        )
