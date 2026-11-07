"""HSM simulado: PAN cifrado, PIN Block ISO 9564-1 formato 4 e IBM 3624 PIN Offset."""

import json
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from pydantic import SecretStr

from app.core.security import hsm
from app.core.security.hsm import (
    ClaveNoAutorizada,
    HsmNoDisponible,
    HsmSimulado,
    PinBlockInvalido,
    PinDebil,
    datos_validacion,
    es_pin_debil,
)
from tests.tarjetas_hsm import HSM, PAN, REFERENCIA

OTRO_PAN = "5000001111111116"


def _abrir_iso4(bloque: str, clave: bytes, pan: str) -> bytes:
    """Descifrado ISO-4 independiente del simulador, para comprobar la estructura."""

    def aes_d(dato: bytes) -> bytes:
        d = Cipher(algorithms.AES(clave), modes.ECB()).decryptor()  # nosec B305
        return d.update(dato) + d.finalize()

    campo_pan = bytes.fromhex(f"{len(pan) - 12:X}{pan}".ljust(32, "0"))
    intermedio = aes_d(bytes.fromhex(bloque))
    return aes_d(bytes(a ^ b for a, b in zip(intermedio, campo_pan, strict=True)))


# PAN


def test_pan_cifrado_ida_y_vuelta_sin_texto_claro():
    cifrado, referencia = HSM.cifrar_pan(PAN, 301)

    assert PAN.encode() not in cifrado
    assert HSM.descifrar_pan(cifrado, referencia, 301) == PAN


def test_pan_cifrado_queda_ligado_a_su_tarjeta():
    cifrado, referencia = HSM.cifrar_pan(PAN, 301)

    with pytest.raises(HsmNoDisponible):
        HSM.descifrar_pan(cifrado, referencia, 302)


def test_pan_no_se_descifra_con_otra_clave():
    cifrado, referencia = HSM.cifrar_pan(PAN, 301)
    otro = HsmSimulado(bytes(32), HSM.clave_pvk, HSM.claves_pin_block, REFERENCIA)

    with pytest.raises(HsmNoDisponible):
        otro.descifrar_pan(cifrado, referencia, 301)


# PIN Block ISO 9564-1 formato 4


def test_pin_block_tiene_la_estructura_iso4():
    bloque, referencia = HSM.construir_pin_block("7392", PAN)

    assert referencia == REFERENCIA and len(bloque) == 32
    campo = _abrir_iso4(bloque, HSM.claves_pin_block[REFERENCIA], PAN).hex().upper()
    # Control 4, longitud 4, PIN, relleno A hasta 16 nibbles y 8 bytes aleatorios
    assert campo[:16] == "447392AAAAAAAAAA"


def test_pin_block_cambia_cada_vez_por_el_relleno_aleatorio():
    assert HSM.construir_pin_block("7392", PAN) != HSM.construir_pin_block("7392", PAN)


def test_pin_block_de_otro_pan_no_abre():
    bloque, referencia = HSM.construir_pin_block("7392", OTRO_PAN)

    with pytest.raises(PinBlockInvalido):
        HSM.generar_offset(bloque, referencia, PAN)


@pytest.mark.parametrize("bloque", ["00" * 16, "0011", "zz" * 16, "00" * 17])
def test_pin_block_mal_formado(bloque):
    with pytest.raises(PinBlockInvalido):
        HSM.generar_offset(bloque, REFERENCIA, PAN)


def test_clave_no_autorizada():
    bloque, _ = HSM.construir_pin_block("7392", PAN)

    with pytest.raises(ClaveNoAutorizada):
        HSM.generar_offset(bloque, "OTRA", PAN)


# IBM 3624 PIN Offset


def test_datos_de_validacion_ibm3624():
    # 12 dígitos a la izquierda del dígito de control, rellenados con F
    assert datos_validacion(PAN) == "000123456789FFFF"


def test_offset_verifica_solo_el_pin_asignado():
    bloque, referencia = HSM.construir_pin_block("7392", PAN)
    offset, pvk = HSM.generar_offset(bloque, referencia, PAN)

    assert len(offset) == 4 and offset.isdigit()
    correcto, _ = HSM.construir_pin_block("7392", PAN)
    incorrecto, _ = HSM.construir_pin_block("7393", PAN)
    assert HSM.verificar_pin(correcto, referencia, PAN, offset, pvk)
    assert not HSM.verificar_pin(incorrecto, referencia, PAN, offset, pvk)


def test_offset_es_pin_menos_pin_natural_digito_a_digito():
    natural = HSM._pin_natural(PAN)
    bloque, referencia = HSM.construir_pin_block("7392", PAN)
    offset, _ = HSM.generar_offset(bloque, referencia, PAN)

    reconstruido = "".join(
        str((int(n) + int(o)) % 10) for n, o in zip(natural, offset, strict=True)
    )
    assert reconstruido == "7392"


def test_offset_depende_de_la_tarjeta():
    # Mismo PIN en dos tarjetas: el PIN natural cambia con el PAN
    assert HSM._pin_natural(PAN) != HSM._pin_natural(OTRO_PAN)


def test_offset_depende_de_la_pvk():
    otro = HsmSimulado(HSM.clave_pan, bytes(16), HSM.claves_pin_block, REFERENCIA)
    assert otro._pin_natural(PAN) != HSM._pin_natural(PAN)


def test_pvk_de_doble_largo_equivale_a_k1k2k1():
    triple = HsmSimulado(
        HSM.clave_pan,
        HSM.clave_pvk + HSM.clave_pvk[:8],
        HSM.claves_pin_block,
        REFERENCIA,
    )
    assert triple._pin_natural(PAN) == HSM._pin_natural(PAN)


def test_verificar_con_pvk_desconocida_falla():
    bloque, referencia = HSM.construir_pin_block("7392", PAN)

    with pytest.raises(HsmNoDisponible):
        HSM.verificar_pin(bloque, referencia, PAN, "1234", "OTRA-PVK")


@pytest.mark.parametrize("offset", ["", "12", "12345", "abcd"])
def test_offset_mal_formado_no_verifica(offset):
    bloque, referencia = HSM.construir_pin_block("7392", PAN)

    assert not HSM.verificar_pin(bloque, referencia, PAN, offset, hsm.REFERENCIA_PVK)


@pytest.mark.parametrize("pin", ["0000", "1111", "1234", "4321", "6789", "9876"])
def test_pin_debil_no_genera_offset(pin):
    bloque, referencia = HSM.construir_pin_block(pin, PAN)

    with pytest.raises(PinDebil):
        HSM.generar_offset(bloque, referencia, PAN)


@pytest.mark.parametrize("pin", ["739", "73925", "", "١٢٣٤", "12a4"])
def test_pin_que_no_son_4_digitos_es_debil(pin):
    assert es_pin_debil(pin)


# Configuración


def _ajustes(**cambios):
    base = {
        "app_env": "development",
        "hsm_sim_clave_pan": SecretStr("00" * 32),
        "hsm_sim_clave_pvk": SecretStr("11" * 16),
        "hsm_sim_claves_pin_block": {"TEST-KEY-01": SecretStr("22" * 32)},
        "hsm_sim_referencia_pin_block": "TEST-KEY-01",
    }
    return SimpleNamespace(**(base | cambios))


def test_obtener_hsm_con_claves_validas(monkeypatch):
    monkeypatch.setattr(hsm, "get_settings", lambda: _ajustes())

    assert isinstance(hsm.obtener_hsm(), HsmSimulado)


@pytest.mark.parametrize(
    "cambios",
    [
        {"app_env": "production"},
        {"hsm_sim_clave_pan": SecretStr("")},
        {"hsm_sim_clave_pan": SecretStr("00" * 16)},
        {"hsm_sim_clave_pvk": SecretStr("11" * 8)},
        {"hsm_sim_clave_pvk": SecretStr("no-hex")},
        {"hsm_sim_claves_pin_block": {}},
        {"hsm_sim_claves_pin_block": {"TEST-KEY-01": SecretStr("22" * 16)}},
        {"hsm_sim_referencia_pin_block": "OTRA"},
    ],
)
def test_sin_hsm_en_produccion_ni_con_claves_invalidas(monkeypatch, cambios):
    monkeypatch.setattr(hsm, "get_settings", lambda: _ajustes(**cambios))

    with pytest.raises(HsmNoDisponible):
        hsm.obtener_hsm()


def test_claves_del_pin_block_se_leen_como_json(monkeypatch):
    from app.core.config.settings import Settings

    monkeypatch.setenv(
        "HSM_SIM_CLAVES_PIN_BLOCK", json.dumps({"TEST-KEY-01": "22" * 32})
    )
    ajustes = Settings(_env_file=None)  # type: ignore[call-arg]

    clave = ajustes.hsm_sim_claves_pin_block["TEST-KEY-01"]
    assert clave.get_secret_value() == "22" * 32
    assert "22" * 32 not in repr(ajustes)
