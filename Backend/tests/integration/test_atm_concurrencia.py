import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.core.database.db import get_engine
from app.modules.atm.repository import obtener_pin_para_verificacion

ID_TARJETA_PRUEBA = 1


@pytest.mark.integration
def test_updlock_serializa_acceso():
    if os.getenv("ATM_INTEGRATION_DB_ENABLED") != "1":
        pytest.skip(
            "Prueba de integración ATM deshabilitada. "
            "Configurar ATM_INTEGRATION_DB_ENABLED=1 "
            "y una base SeguridadDB de pruebas."
        )

    engine = get_engine("seguridad")

    primer_bloqueo = threading.Event()
    liberar_bloqueo = threading.Event()
    segundo_finalizado = threading.Event()

    def primera_solicitud():
        with engine.begin() as conn:
            estado = obtener_pin_para_verificacion(
                conn,
                ID_TARJETA_PRUEBA,
            )

            assert estado is not None

            primer_bloqueo.set()

            if not liberar_bloqueo.wait(timeout=20):
                raise TimeoutError("No se liberó el primer bloqueo.")

    def segunda_solicitud():
        with engine.begin() as conn:
            estado = obtener_pin_para_verificacion(
                conn,
                ID_TARJETA_PRUEBA,
            )

            assert estado is not None
            segundo_finalizado.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futuro_1 = executor.submit(primera_solicitud)

        if not primer_bloqueo.wait(timeout=20):
            liberar_bloqueo.set()

            if futuro_1.done():
                futuro_1.result()

            raise AssertionError(
                "La primera solicitud no adquirió el bloqueo "
                "en 20 segundos. Puede existir un problema de conexión "
                "o una consulta SQL bloqueada."
            )

        futuro_2 = executor.submit(segunda_solicitud)

        try:
            time.sleep(1)

            assert not segundo_finalizado.is_set(), (
                "La segunda solicitud no esperó el bloqueo de la primera."
            )
        finally:
            liberar_bloqueo.set()

        futuro_1.result(timeout=15)
        futuro_2.result(timeout=15)

    assert segundo_finalizado.is_set()
