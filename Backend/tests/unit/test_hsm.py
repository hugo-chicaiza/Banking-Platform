"""Pruebas criptográficas locales con claves y PAN ficticios; nunca leen el .env."""

from dataclasses import replace

import pytest
from pydantic import SecretStr

from app.core.config.settings import Settings
from app.core.security import hsm as modulo
from app.core.security.hsm import (
    ClaveNoAutorizada,
    HsmNoDisponible,
    HsmSimulado,
    PinBlockInvalido,
    PinDebil,
)

PAN = "5000001234567896"
PIN = "7392"
REFERENCIA = "TEST-KEY-01"
CLAVE_AES = bytes(range(32, 64))
HSM = HsmSimulado(
    clave_pan=bytes(range(32)),
    clave_pvk=bytes(range(100, 116)),
    claves_pin_block={REFERENCIA: CLAVE_AES},
    referencia_pin_block=REFERENCIA,
)
# Vectores fijos de laboratorio, independientes del generador del simulador:
# ISO-4: campo PIN 447392AAAAAAAAAA0011223344556677, campo PAN
# 45000001234567896000000000000000 y AES-256 bytes(range(32, 64)).
BLOQUE_CONOCIDO = "AEC527BE349D702DEB16B69564DBECD1"


@pytest.fixture(autouse=True)
def sin_base_de_datos(monkeypatch):
    def prohibido(*args, **kwargs):
        raise AssertionError("Estas pruebas no pueden conectarse a una base de datos")

    monkeypatch.setattr("pyodbc.connect", prohibido)
    monkeypatch.setattr("sqlalchemy.create_engine", prohibido)
    monkeypatch.setattr("app.core.database.db.create_engine", prohibido)


def test_aes256_vector_conocido():
    # Vector AES-256 de un bloque (NIST SP 800-38A).
    clave = bytes.fromhex(
        "603deb1015ca71be2b73aef0857d77811f352c073b6108d72d9810a30914dff4"
    )
    claro = bytes.fromhex("6bc1bee22e409f96e93d7e117393172a")
    cifrado = bytes.fromhex("f3eed1bdb5d2a03c064b5a7e3db181f8")
    assert modulo._aes_bloque(clave, claro, True) == cifrado
    assert modulo._aes_bloque(clave, cifrado, False) == claro


def test_parametros_ibm3624_y_campo_pan_iso4():
    assert modulo.LONGITUD_PIN == 4
    assert modulo.TABLA_DECIMALIZACION == "0123456789012345"
    assert modulo.RELLENO_VALIDACION == "F"
    assert modulo.datos_validacion(PAN) == "000123456789FFFF"
    assert modulo._campo_pan(PAN).hex().upper() == "45000001234567896000000000000000"


def test_iso4_abre_vector_conocido():
    assert HSM._abrir_pin_block(BLOQUE_CONOCIDO, REFERENCIA, PAN) == PIN


def test_iso4_construye_campo_pin_y_usa_relleno_aleatorio():
    primero, referencia = HSM.construir_pin_block(PIN, PAN)
    segundo, _ = HSM.construir_pin_block(PIN, PAN)
    assert referencia == REFERENCIA
    assert len(bytes.fromhex(primero)) == 16
    assert primero != segundo
    campo = modulo._campo_pin(PIN)
    assert len(campo) == 16
    assert campo[:8].hex().upper() == "447392AAAAAAAAAA"
    assert HSM._abrir_pin_block(primero, referencia, PAN) == PIN


@pytest.mark.parametrize(
    "largo_pvk,natural,offset",
    [(16, "5190", "2202"), (24, "9601", "8791")],
)
def test_ibm3624_vectores_fijos_y_offset(largo_pvk, natural, offset):
    # 3DES sobre 000123456789FFFF: FB9AEF6975A177A5 (PVK doble)
    # y 960B5A9C2CF2DA3B (PVK triple), decimalizados con la tabla compartida.
    hsm = replace(HSM, clave_pvk=bytes(range(100, 100 + largo_pvk)))
    assert hsm._pin_natural(PAN) == natural
    assert hsm.generar_offset(BLOQUE_CONOCIDO, REFERENCIA, PAN) == (
        offset,
        "SIM-PVK-01",
    )
    assert hsm.verificar_pin(BLOQUE_CONOCIDO, REFERENCIA, PAN, offset, "SIM-PVK-01")


@pytest.mark.parametrize("pin_ingresado,correcto", [(PIN, True), ("4826", False)])
def test_generar_y_verificar_con_bloque_nuevo(pin_ingresado, correcto):
    bloque_inicial, ref = HSM.construir_pin_block(PIN, PAN)
    offset, pvk = HSM.generar_offset(bloque_inicial, ref, PAN)
    bloque_nuevo, ref = HSM.construir_pin_block(pin_ingresado, PAN)
    assert HSM.verificar_pin(bloque_nuevo, ref, PAN, offset, pvk) is correcto


@pytest.mark.parametrize("operacion", ["generar_offset", "verificar_pin"])
def test_referencia_pin_block_no_autorizada(operacion):
    with pytest.raises(ClaveNoAutorizada):
        if operacion == "generar_offset":
            HSM.generar_offset(BLOQUE_CONOCIDO, "DESCONOCIDA", PAN)
        else:
            HSM.verificar_pin(BLOQUE_CONOCIDO, "DESCONOCIDA", PAN, "2202", "SIM-PVK-01")


def test_referencia_pvk_desconocida():
    with pytest.raises(HsmNoDisponible):
        HSM.verificar_pin(BLOQUE_CONOCIDO, REFERENCIA, PAN, "2202", "OTRA-PVK")


def test_pin_block_admite_solo_claves_autorizadas_y_elige_por_referencia():
    otra = replace(
        HSM,
        claves_pin_block={REFERENCIA: CLAVE_AES, "TEST-KEY-02": bytes(range(64, 96))},
        referencia_pin_block="TEST-KEY-02",
    )
    bloque, ref = otra.construir_pin_block(PIN, PAN)
    assert ref == "TEST-KEY-02"
    assert otra.generar_offset(bloque, ref, PAN) == ("2202", "SIM-PVK-01")


@pytest.mark.parametrize("bloque", ["", "00" * 15, "00" * 17, "Z" * 32])
def test_bloque_hex_invalido(bloque):
    with pytest.raises(PinBlockInvalido):
        HSM.verificar_pin(bloque, REFERENCIA, PAN, "2202", "SIM-PVK-01")


@pytest.mark.parametrize(
    "campo",
    [
        "347392AAAAAAAAAA0011223344556677",  # Control distinto de 4.
        "43739AAAAAAAAAAA0011223344556677",  # Longitud inferior a 4.
        "4D739200000000000011223344556677",  # Longitud superior a 12.
        "44739BAAAAAAAAAA0011223344556677",  # PIN no decimal.
        "447392BAAAAAAAAA0011223344556677",  # Relleno distinto de A.
    ],
)
def test_estructura_iso4_invalida_con_cifrado_real(campo):
    intermedio = modulo._aes_bloque(CLAVE_AES, bytes.fromhex(campo), True)
    cifrado = modulo._aes_bloque(
        CLAVE_AES, modulo._xor(intermedio, modulo._campo_pan(PAN)), True
    )
    with pytest.raises(PinBlockInvalido):
        HSM.generar_offset(cifrado.hex(), REFERENCIA, PAN)


@pytest.mark.parametrize("pin", ["0000", "1111", "1234", "4321", "73920"])
def test_generacion_rechaza_pin_debil(pin):
    bloque, ref = HSM.construir_pin_block(pin, PAN)
    with pytest.raises(PinDebil):
        HSM.generar_offset(bloque, ref, PAN)


@pytest.mark.parametrize("offset", ["", "123", "12345", "12X4"])
def test_simulador_rechaza_offset_invalido(offset):
    assert not HSM.verificar_pin(BLOQUE_CONOCIDO, REFERENCIA, PAN, offset, "SIM-PVK-01")


def test_pan_cifrado_se_recupera_y_cada_cifrado_usa_nonce_nuevo():
    cifrado, ref = HSM.cifrar_pan(PAN, 1)
    otro, _ = HSM.cifrar_pan(PAN, 1)
    assert ref == "SIM-PAN-01"
    assert PAN.encode() not in cifrado
    assert cifrado != otro
    assert HSM.descifrar_pan(cifrado, ref, 1) == PAN


@pytest.mark.parametrize(
    "fallo", ["otra_tarjeta", "otra_clave", "alterado", "referencia"]
)
def test_pan_cifrado_rechaza_custodia_invalida(fallo):
    cifrado, ref = HSM.cifrar_pan(PAN, 1)
    hsm, id_tarjeta = HSM, 1
    if fallo == "otra_tarjeta":
        id_tarjeta = 2
    elif fallo == "otra_clave":
        hsm = replace(HSM, clave_pan=bytes(range(32, 64)))
    elif fallo == "alterado":
        cifrado = cifrado[:-1] + bytes([cifrado[-1] ^ 1])
    else:
        ref = "OTRA-CLAVE-PAN"
    with pytest.raises(HsmNoDisponible):
        hsm.descifrar_pan(cifrado, ref, id_tarjeta)


@pytest.fixture
def configuracion(monkeypatch):
    settings = Settings.model_construct(
        app_env="development",
        hsm_sim_clave_pan=SecretStr(HSM.clave_pan.hex()),
        hsm_sim_clave_pvk=SecretStr(HSM.clave_pvk.hex()),
        hsm_sim_claves_pin_block={REFERENCIA: SecretStr(CLAVE_AES.hex())},
        hsm_sim_referencia_pin_block=REFERENCIA,
    )
    monkeypatch.setattr(modulo, "get_settings", lambda: settings)
    return settings


def test_factory_usa_configuracion_local_sin_mockear_criptografia(configuracion):
    hsm = modulo.obtener_hsm()
    assert hsm.generar_offset(BLOQUE_CONOCIDO, REFERENCIA, PAN) == (
        "2202",
        "SIM-PVK-01",
    )


def test_factory_prohibe_simulador_en_produccion(configuracion):
    configuracion.app_env = "production"
    with pytest.raises(HsmNoDisponible):
        modulo.obtener_hsm()


@pytest.mark.parametrize(
    "campo,valor",
    [
        ("hsm_sim_clave_pan", SecretStr("")),
        ("hsm_sim_clave_pan", SecretStr("ZZ" * 32)),
        ("hsm_sim_clave_pvk", SecretStr("00" * 8)),
        ("hsm_sim_claves_pin_block", {REFERENCIA: SecretStr("00" * 16)}),
        ("hsm_sim_referencia_pin_block", "NO-AUTORIZADA"),
    ],
)
def test_factory_traduce_configuracion_invalida(configuracion, campo, valor):
    setattr(configuracion, campo, valor)
    with pytest.raises(HsmNoDisponible):
        modulo.obtener_hsm()
