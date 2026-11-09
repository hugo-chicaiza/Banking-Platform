"""Arnes de dos conexiones para comprobar serializacion SQL y rollback."""

import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event


def comprobar_serializacion(engine, bloquear_primero, bloquear_segundo=None):
    listo, intentado, liberar = Event(), Event(), Event()
    segunda_operacion = bloquear_segundo or bloquear_primero

    def trabajador(primero):
        if not primero:
            assert listo.wait(4)
        with engine.connect() as conn:
            tx = conn.begin()
            try:
                if primero:
                    bloquear_primero(conn)
                    listo.set()
                    assert liberar.wait(4)
                else:
                    intentado.set()
                    segunda_operacion(conn)
            finally:
                tx.rollback()

    with ThreadPoolExecutor(2) as pool:
        a = pool.submit(trabajador, True)
        b = pool.submit(trabajador, False)
        try:
            assert intentado.wait(4)
            time.sleep(0.25)
            solapamiento = not b.done()
        finally:
            liberar.set()
        a.result(timeout=6)
        b.result(timeout=6)
    assert solapamiento
