from functools import lru_cache

from app.core.config.settings import get_settings

from .simulator import SimulatedHsm
from .test_pan_repository import PanFicticioRepository


@lru_cache
def get_hsm() -> SimulatedHsm:
    settings = get_settings()

    return SimulatedHsm(
        test_key=bytes.fromhex(settings.atm_hsm_aes_key_hex),
        pin_generation_key=bytes.fromhex(settings.atm_hsm_pin_generation_key_hex),
        key_reference=settings.atm_hsm_key_reference,
    )


@lru_cache
def get_pan_repository() -> PanFicticioRepository:
    settings = get_settings()

    if settings.app_env not in ("development", "staging"):
        raise RuntimeError(
            "Los PAN ficticios solo están permitidos en desarrollo y staging."
        )

    return PanFicticioRepository()
