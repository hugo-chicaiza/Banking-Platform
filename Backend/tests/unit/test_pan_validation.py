import pytest

from app.core.security.hsm import HsmSimulado
from app.modules.atm.hsm.pan_validation import validar_hash_pan

HSM = HsmSimulado(
    clave_pan=bytes(32),
    clave_pvk=bytes(16),
    claves_pin_block={"TEST-KEY-01": bytes(32)},
    referencia_pin_block="TEST-KEY-01",
    clave_hmac_pan=bytes(range(32)),
)


def test_pan_correcto():
    pan = "432198765432109870"
    hash_pan = HSM.huella_pan(pan).hex()

    assert validar_hash_pan(pan, hash_pan, HSM) is True


def test_pan_incorrecto():
    pan = "432198765432109870"
    otro_pan = "432198765432109871"
    hash_pan = HSM.huella_pan(otro_pan).hex()

    assert validar_hash_pan(pan, hash_pan, HSM) is False


def test_pan_invalido():
    assert validar_hash_pan("PAN-INVALIDO", "abc", HSM) is False


@pytest.mark.parametrize("tipo", [bytes, bytearray, memoryview])
def test_hash_binario_de_tar01(tipo):
    pan = "5000001234567896"
    huella = HSM.huella_pan(pan)
    assert validar_hash_pan(pan, tipo(huella), HSM)
    assert not validar_hash_pan(pan, tipo(bytes(32)), HSM)
