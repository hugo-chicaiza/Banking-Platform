"""Repositorio de PAN ficticios exclusivo para pruebas locales."""

import os


class PanFicticioRepository:
    """Almacena PAN ficticios en memoria, nunca tarjetas reales."""

    def __init__(self) -> None:
        if os.getenv("APP_ENV", "").lower() not in {
            "local",
            "development",
            "test",
            "staging",
        }:
            raise RuntimeError(
                "El repositorio de PAN ficticios "
                "solo puede utilizarse en desarrollo y pruebas."
            )

        self._tarjetas: dict[int, str] = {}

    def registrar(self, id_tarjeta: int, pan: str) -> None:
        if id_tarjeta <= 0:
            raise ValueError("ID de tarjeta no válido")

        if not pan.isascii() or not pan.isdigit():
            raise ValueError("PAN ficticio no válido")

        if not 12 <= len(pan) <= 19:
            raise ValueError("Longitud de PAN no válida")

        self._tarjetas[id_tarjeta] = pan

    def obtener(self, id_tarjeta: int) -> str | None:
        return self._tarjetas.get(id_tarjeta)
