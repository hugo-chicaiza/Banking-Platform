import hmac

from .ibm3624 import calcular_pin_natural, generar_offset
from .interface import (
    HsmInterface,
    PinGenerationRequest,
    PinVerificationRequest,
)
from .iso4 import descifrar_pin_block_iso4


class SimulatedHsm(HsmInterface):
    """Simulador HSM exclusivo para desarrollo y pruebas."""

    def __init__(
        self,
        test_key: bytes,
        pin_generation_key: bytes,
        key_reference: str = "TEST-KEY-01",
    ) -> None:
        if len(test_key) != 32:
            raise ValueError("La clave AES-256 debe tener 32 bytes")

        if len(pin_generation_key) not in (16, 24):
            raise ValueError("La clave IBM 3624 debe tener 16 o 24 bytes")

        self._key = test_key
        self._pin_generation_key = pin_generation_key
        self._key_reference = key_reference

    def _obtener_pin(
        self,
        encrypted_pin_block: bytes,
        pan: str,
        key_reference: str,
    ) -> str:
        if key_reference != self._key_reference:
            raise ValueError("Referencia de clave desconocida")

        return descifrar_pin_block_iso4(
            pin_block_cifrado=encrypted_pin_block,
            pan=pan,
            clave=self._key,
        )

    async def generate_pin_offset(
        self,
        request: PinGenerationRequest,
    ) -> str:
        """Genera el Offset IBM 3624 para TAR-05."""

        pin = self._obtener_pin(
            request.encrypted_pin_block,
            request.pan,
            request.key_reference,
        )

        pin_natural = calcular_pin_natural(
            validation_data=request.validation_data,
            pin_generation_key=self._pin_generation_key,
            pin_length=len(pin),
        )

        return generar_offset(pin, pin_natural)

    async def verify_pin(
        self,
        request: PinVerificationRequest,
    ) -> bool:
        """Verifica el PIN mediante el Offset registrado."""

        pin = self._obtener_pin(
            request.encrypted_pin_block,
            request.pan,
            request.key_reference,
        )

        pin_natural = calcular_pin_natural(
            validation_data=request.validation_data,
            pin_generation_key=self._pin_generation_key,
            pin_length=len(pin),
        )

        offset_calculado = generar_offset(pin, pin_natural)

        return hmac.compare_digest(
            offset_calculado,
            request.pin_offset,
        )
