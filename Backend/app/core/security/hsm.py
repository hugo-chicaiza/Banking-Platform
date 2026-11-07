"""HSM simulado para tarjetas (TAR-01, TAR-05 y ATM-01).

Solo para desarrollo y pruebas, con claves ficticias de la configuración. No es un HSM
certificado ni cumple ISO 9564, PCI DSS o PCI PIN. En producción no hay simulador:
`obtener_hsm` lanza HsmNoDisponible hasta integrar el HSM de pagos (ver
Backend/docs/HSM-Thales.md). Las reglas de negocio solo usan la interfaz `Hsm`.

Operaciones:
- PAN: AES-256-GCM, ligado al IdTarjeta (dato asociado). Es el "PAN cifrado por HSM".
- PIN Block: ISO 9564-1 formato 4 con AES-256. La clave se elige por keyReference,
  solo entre las autorizadas en el servidor.
- PIN Offset: IBM 3624 con una PVK 3DES independiente de la clave del PIN Block.

Ningún método devuelve el PIN en claro: el PIN solo existe dentro del simulador.
"""

import hmac
import os
import secrets
from dataclasses import dataclass
from itertools import pairwise
from typing import Protocol

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.decrepit.ciphers.algorithms import TripleDES
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config.settings import get_settings

# Referencias de las claves del simulador que se guardan junto a cada dato
REFERENCIA_PAN = "SIM-PAN-01"
REFERENCIA_PVK = "SIM-PVK-01"

# Parámetros de IBM 3624. TAR-05 y ATM-01 deben usar exactamente los mismos
LONGITUD_PIN = 4
TABLA_DECIMALIZACION = "0123456789012345"
# Datos de validación: los 12 dígitos del PAN a la izquierda del dígito de control,
# completados a 16 caracteres hexadecimales con este relleno
RELLENO_VALIDACION = "F"

_NONCE_GCM = 12
_BLOQUE = 16


class ErrorHsm(Exception):
    """Base de los errores del HSM. El mensaje nunca lleva datos sensibles."""


class HsmNoDisponible(ErrorHsm):
    """No hay HSM configurado (producción o claves ausentes) o falló la operación."""


class ClaveNoAutorizada(ErrorHsm):
    """La keyReference no está en la configuración autorizada del servidor."""


class PinBlockInvalido(ErrorHsm):
    """El PIN Block no tiene el formato o la estructura de ISO 9564-1 formato 4."""


class PinDebil(ErrorHsm):
    """El PIN no tiene 4 dígitos o es trivial (repetido o secuencia)."""


class Hsm(Protocol):
    def cifrar_pan(self, pan: str, id_tarjeta: int) -> tuple[bytes, str]:
        """Devuelve (PAN cifrado, referencia de clave)."""
        ...

    def descifrar_pan(
        self, cifrado: bytes, referencia: str, id_tarjeta: int
    ) -> str: ...

    def construir_pin_block(self, pin: str, pan: str) -> tuple[str, str]:
        """Simula el PIN pad: (PIN Block ISO-4 cifrado en hex, keyReference)."""
        ...

    def generar_offset(
        self, pin_block: str, referencia: str, pan: str
    ) -> tuple[str, str]:
        """(PIN Offset IBM 3624, referencia de la PVK). Valida la fortaleza del PIN."""
        ...

    def verificar_pin(
        self,
        pin_block: str,
        referencia: str,
        pan: str,
        offset: str,
        referencia_pvk: str,
    ) -> bool: ...


def es_pin_debil(pin: str) -> bool:
    """True si no son 4 dígitos, o si es repetido (0000) o secuencia (1234, 4321)."""
    if len(pin) != LONGITUD_PIN or not (pin.isascii() and pin.isdigit()):
        return True
    saltos = {int(b) - int(a) for a, b in pairwise(pin)}
    return saltos in ({0}, {1}, {-1})


def datos_validacion(pan: str) -> str:
    """IBM 3624: 12 dígitos del PAN sin el de control, rellenados a 16 hex."""
    return pan[-13:-1].ljust(16, RELLENO_VALIDACION)


def _aes_bloque(clave: bytes, bloque: bytes, cifrar: bool) -> bytes:
    # ISO 9564-1 formato 4 define el cifrado de un único bloque de 16 bytes con AES:
    # ECB sobre un bloque es el modo que pide la norma, no un uso genérico de ECB.
    cipher = Cipher(algorithms.AES(clave), modes.ECB())  # nosec B305 # NOSONAR
    operacion = cipher.encryptor() if cifrar else cipher.decryptor()
    return operacion.update(bloque) + operacion.finalize()


def _xor(a: bytes, b: bytes) -> bytes:
    return bytes(x ^ y for x, y in zip(a, b, strict=True))


def _campo_pan(pan: str) -> bytes:
    """ISO-4: longitud del PAN menos 12 en el primer nibble, el PAN y ceros."""
    return bytes.fromhex(f"{len(pan) - 12:X}{pan}".ljust(32, "0"))


def _campo_pin(pin: str) -> bytes:
    """ISO-4: control 4, longitud, PIN, relleno A hasta 16 nibbles y 8 bytes al azar."""
    texto = f"4{len(pin):X}{pin}".ljust(16, "A")
    return bytes.fromhex(texto) + secrets.token_bytes(8)


def _leer_campo_pin(campo: bytes) -> str:
    texto = campo.hex().upper()
    if texto[0] != "4":
        raise PinBlockInvalido("Control distinto de 4")
    longitud = int(texto[1], 16)
    if not 4 <= longitud <= 12:
        raise PinBlockInvalido("Longitud de PIN fuera de rango")
    pin = texto[2 : 2 + longitud]
    relleno = texto[2 + longitud : 16]
    if not pin.isdigit() or set(relleno) - {"A"}:
        raise PinBlockInvalido("Estructura del PIN Block inválida")
    return pin


def _bytes_hex(valor: str, largo: int) -> bytes:
    try:
        datos = bytes.fromhex(valor)
    except ValueError:
        raise PinBlockInvalido("No es hexadecimal") from None
    if len(datos) != largo:
        raise PinBlockInvalido("Largo inválido")
    return datos


@dataclass(frozen=True)
class HsmSimulado:
    clave_pan: bytes
    clave_pvk: bytes
    claves_pin_block: dict[str, bytes]
    referencia_pin_block: str

    # --- PAN -------------------------------------------------------------------------

    def cifrar_pan(self, pan: str, id_tarjeta: int) -> tuple[bytes, str]:
        nonce = os.urandom(_NONCE_GCM)
        cifrado = AESGCM(self.clave_pan).encrypt(
            nonce, pan.encode(), _dato_asociado(id_tarjeta)
        )
        return nonce + cifrado, REFERENCIA_PAN

    def descifrar_pan(self, cifrado: bytes, referencia: str, id_tarjeta: int) -> str:
        if referencia != REFERENCIA_PAN:
            raise HsmNoDisponible("Referencia de clave de PAN desconocida")
        try:
            claro = AESGCM(self.clave_pan).decrypt(
                cifrado[:_NONCE_GCM], cifrado[_NONCE_GCM:], _dato_asociado(id_tarjeta)
            )
        except InvalidTag:
            # Otra clave o el cifrado de otra tarjeta: nunca se devuelve un PAN ajeno
            raise HsmNoDisponible("No se pudo descifrar el PAN") from None
        return claro.decode()

    # --- PIN Block ISO 9564-1 formato 4 ----------------------------------------------

    def _clave_pin_block(self, referencia: str) -> bytes:
        clave = self.claves_pin_block.get(referencia)
        if clave is None:
            raise ClaveNoAutorizada("keyReference no autorizada")
        return clave

    def construir_pin_block(self, pin: str, pan: str) -> tuple[str, str]:
        clave = self._clave_pin_block(self.referencia_pin_block)
        intermedio = _aes_bloque(clave, _campo_pin(pin), cifrar=True)
        final = _aes_bloque(clave, _xor(intermedio, _campo_pan(pan)), cifrar=True)
        return final.hex().upper(), self.referencia_pin_block

    def _abrir_pin_block(self, pin_block: str, referencia: str, pan: str) -> str:
        clave = self._clave_pin_block(referencia)
        cifrado = _bytes_hex(pin_block, _BLOQUE)
        intermedio = _aes_bloque(clave, cifrado, cifrar=False)
        campo = _aes_bloque(clave, _xor(intermedio, _campo_pan(pan)), cifrar=False)
        return _leer_campo_pin(campo)

    # --- IBM 3624 PIN Offset ---------------------------------------------------------

    def _pin_natural(self, pan: str) -> str:
        # PVK de doble largo (K1K2) se expande a K1K2K1: es el mismo 3DES
        clave = (
            self.clave_pvk + self.clave_pvk[:8]
            if len(self.clave_pvk) == 16
            else self.clave_pvk
        )
        # IBM 3624 está definido sobre DES/3DES en ECB (ver issue TAR-05): la norma lo
        # exige y la clave nunca sale del HSM simulado
        cipher = Cipher(TripleDES(clave), modes.ECB())  # nosec B304 B305 # NOSONAR
        cifrador = cipher.encryptor()
        resultado = cifrador.update(bytes.fromhex(datos_validacion(pan)))
        resultado += cifrador.finalize()
        decimal = "".join(TABLA_DECIMALIZACION[int(c, 16)] for c in resultado.hex())
        return decimal[:LONGITUD_PIN]

    def generar_offset(
        self, pin_block: str, referencia: str, pan: str
    ) -> tuple[str, str]:
        pin = self._abrir_pin_block(pin_block, referencia, pan)
        if es_pin_debil(pin):
            raise PinDebil("PIN no permitido")
        natural = self._pin_natural(pan)
        offset = "".join(
            str((int(p) - int(n)) % 10) for p, n in zip(pin, natural, strict=True)
        )
        return offset, REFERENCIA_PVK

    def verificar_pin(
        self,
        pin_block: str,
        referencia: str,
        pan: str,
        offset: str,
        referencia_pvk: str,
    ) -> bool:
        if referencia_pvk != REFERENCIA_PVK:
            raise HsmNoDisponible("Referencia de PVK desconocida")
        if len(offset) != LONGITUD_PIN or not offset.isdigit():
            return False
        pin = self._abrir_pin_block(pin_block, referencia, pan)
        natural = self._pin_natural(pan)
        esperado = "".join(
            str((int(n) + int(o)) % 10) for n, o in zip(natural, offset, strict=True)
        )
        return hmac.compare_digest(pin, esperado)


def _dato_asociado(id_tarjeta: int) -> bytes:
    return f"IdTarjeta={id_tarjeta}".encode()


def _clave(valor: str, largos: tuple[int, ...]) -> bytes:
    datos = bytes.fromhex(valor)
    if len(datos) not in largos:
        raise ValueError("Largo de clave inválido")
    return datos


def obtener_hsm() -> Hsm:
    """El simulador fuera de producción y con todas sus claves configuradas."""
    s = get_settings()
    if s.app_env == "production":
        raise HsmNoDisponible("Sin HSM de pagos en producción")
    try:
        claves_pin_block = {
            ref: _clave(clave.get_secret_value(), (32,))
            for ref, clave in s.hsm_sim_claves_pin_block.items()
        }
        hsm = HsmSimulado(
            clave_pan=_clave(s.hsm_sim_clave_pan.get_secret_value(), (32,)),
            clave_pvk=_clave(s.hsm_sim_clave_pvk.get_secret_value(), (16, 24)),
            claves_pin_block=claves_pin_block,
            referencia_pin_block=s.hsm_sim_referencia_pin_block,
        )
    except ValueError:
        raise HsmNoDisponible("Claves del HSM simulado ausentes o inválidas") from None
    if hsm.referencia_pin_block not in claves_pin_block:
        raise HsmNoDisponible("La referencia por defecto no tiene clave")
    return hsm
