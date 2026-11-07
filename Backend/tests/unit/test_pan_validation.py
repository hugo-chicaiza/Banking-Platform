import hashlib

import pytest

from app.modules.atm.hsm.pan_validation import validar_hash_pan


def test_pan_correcto():
    pan = "432198765432109870"
    hash_pan = hashlib.sha256(pan.encode("ascii")).hexdigest()

    assert validar_hash_pan(pan, hash_pan) is True


def test_pan_incorrecto():
    pan = "432198765432109870"
    otro_pan = "432198765432109871"
    hash_pan = hashlib.sha256(otro_pan.encode("ascii")).hexdigest()

    assert validar_hash_pan(pan, hash_pan) is False


def test_pan_invalido():
    assert validar_hash_pan("PAN-INVALIDO", "abc") is False


@pytest.mark.parametrize("tipo", [bytes, bytearray, memoryview])
def test_hash_binario_de_tar01(tipo):
    pan = "5000001234567896"
    assert validar_hash_pan(pan, tipo(hashlib.sha256(pan.encode()).digest()))
    assert not validar_hash_pan(pan, tipo(bytes(32)))
