from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class PinGenerationRequest:
    encrypted_pin_block: bytes
    pan: str
    key_reference: str
    validation_data: str


@dataclass(frozen=True)
class PinVerificationRequest:
    encrypted_pin_block: bytes
    pan: str
    key_reference: str
    validation_data: str
    pin_offset: str


class HsmInterface(ABC):
    @abstractmethod
    async def generate_pin_offset(
        self,
        request: PinGenerationRequest,
    ) -> str:
        """Genera un IBM 3624 PIN Offset sin devolver el PIN."""
        ...

    @abstractmethod
    async def verify_pin(
        self,
        request: PinVerificationRequest,
    ) -> bool:
        """Verifica el PIN mediante IBM 3624 PIN Offset."""
        ...
