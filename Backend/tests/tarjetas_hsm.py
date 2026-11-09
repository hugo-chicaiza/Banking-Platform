"""Apoyo de pruebas de tarjetas: HSM simulado con claves fijas y SeguridadDB en memoria.

Reemplaza solo las funciones del repositorio que tocan SeguridadDB (PAN ficticio y
TarjetaPIN); el HSM es el simulador real, así que la generación del PIN y el Offset
IBM 3624 se prueban de punta a punta.
"""

from dataclasses import dataclass, field
from typing import Any

from app.core.security.hsm import HsmSimulado
from app.modules.tarjetas import repository, service

REFERENCIA = "TEST-KEY-01"
HSM = HsmSimulado(
    clave_pan=bytes(range(32)),
    clave_pvk=bytes(range(100, 116)),
    claves_pin_block={REFERENCIA: bytes(range(32, 64))},
    referencia_pin_block=REFERENCIA,
)
# PAN ficticio de la tarjeta 301 (BIN de prueba 500000, Luhn válido)
PAN = "5000001234567896"


@dataclass
class SeguridadEnMemoria:
    """Pruebas.PanFicticio y Tarjetas.TarjetaPIN."""

    pans: dict[int, tuple[bytes, str]] = field(default_factory=dict)
    pines: dict[int, dict[str, Any]] = field(default_factory=dict)

    def custodiar(self, id_tarjeta: int = 301, pan: str = PAN) -> None:
        self.pans[id_tarjeta] = HSM.cifrar_pan(pan, id_tarjeta)

    def pin(self, id_tarjeta: int = 301) -> dict[str, Any]:
        return self.pines[id_tarjeta]


def instalar(monkeypatch) -> SeguridadEnMemoria:
    memoria = SeguridadEnMemoria()
    monkeypatch.setattr(service, "obtener_hsm", lambda: HSM)

    def guardar_pan(_c, id_tarjeta, cifrado, referencia):
        memoria.pans[id_tarjeta] = (cifrado, referencia)

    def guardar_pin(_c, id_tarjeta, offset, referencia_pvk, requiere_cambio):
        memoria.pines[id_tarjeta] = {
            "offset": offset,
            "pvk": referencia_pvk,
            "requiere_cambio": requiere_cambio,
            "estado": "Activo",
            "intentos": 0,
        }

    monkeypatch.setattr(repository, "guardar_pan_ficticio", guardar_pan)
    monkeypatch.setattr(
        repository, "borrar_pan_ficticio", lambda _c, i: memoria.pans.pop(i, None)
    )
    monkeypatch.setattr(
        repository, "obtener_pan_ficticio", lambda _c, i: memoria.pans.get(i)
    )
    monkeypatch.setattr(repository, "guardar_pin_generado", guardar_pin)
    return memoria


def pin_generado(memoria: SeguridadEnMemoria, id_tarjeta: int = 301) -> str:
    """Solo para pruebas: reconstruye el PIN que eligió el HSM (natural + Offset).

    En el sistema nadie puede hacerlo; aquí sirve para probar que ATM-01 lo acepta.
    """
    natural = HSM._pin_natural(PAN)
    offset = memoria.pin(id_tarjeta)["offset"]
    return "".join(
        str((int(n) + int(o)) % 10) for n, o in zip(natural, offset, strict=True)
    )


def pin_valido(memoria: SeguridadEnMemoria, pin: str, id_tarjeta: int = 301) -> bool:
    """Verificación como la hará ATM-01: PIN Block nuevo contra el Offset guardado."""
    fila = memoria.pin(id_tarjeta)
    bloque, referencia = HSM.construir_pin_block(pin, PAN)
    return HSM.verificar_pin(bloque, referencia, PAN, fila["offset"], fila["pvk"])


def body_pin(pin: str, pan: str = PAN) -> dict[str, str]:
    """PIN Block ISO-4 tal como lo enviaría el PIN pad del cajero."""
    bloque, referencia = HSM.construir_pin_block(pin, pan)
    return {"encryptedPinBlock": bloque, "keyReference": referencia}
