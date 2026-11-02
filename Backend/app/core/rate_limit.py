"""Límite de peticiones por IP con ventana deslizante en memoria.

Cuenta por proceso, así que con varias instancias o workers el límite real se
multiplica. Con F-03 debería contar por usuario.
"""

import ipaddress
import logging
import math
import time
from collections import OrderedDict, deque
from collections.abc import Callable
from typing import Literal

from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.errors import respuesta_problema

logger = logging.getLogger(__name__)

Clase = Literal["lectura", "escritura", "sensible"]

_VENTANA_SEGUNDOS = 60.0
_MAX_CLAVES = 100_000
_METODOS_LECTURA = {"GET", "HEAD", "OPTIONS"}
# Rutas donde se prueban PIN o credenciales. Algunas son de módulos que aún no existen
_SUFIJOS_SENSIBLES = ("/pin", "/auth/login", "/atm/auth", "/atm/cambio-pin")


class ContadorPeticiones:
    """Guarda las peticiones recientes de cada clave.

    Si hay demasiadas claves descarta las menos usadas, para no crecer sin límite.
    """

    def __init__(
        self,
        ventana: float = _VENTANA_SEGUNDOS,
        max_claves: int = _MAX_CLAVES,
        reloj: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ventana = ventana
        self._max_claves = max_claves
        self._reloj = reloj
        self._claves: OrderedDict[tuple[str, str], deque[float]] = OrderedDict()

    def reiniciar(self) -> None:
        self._claves.clear()

    def registrar(self, clave: tuple[str, str], limite: int) -> float | None:
        """Devuelve None si la petición pasa, o los segundos de espera si excede el límite.

        Las rechazadas no se cuentan: insistir no alarga la espera.
        """
        ahora = self._reloj()
        instantes = self._claves.get(clave)
        if instantes is None:
            instantes = deque()
            self._claves[clave] = instantes
        self._claves.move_to_end(clave)

        while instantes and ahora - instantes[0] >= self._ventana:
            instantes.popleft()
        if len(instantes) >= limite:
            return self._ventana - (ahora - instantes[0])

        instantes.append(ahora)
        while len(self._claves) > self._max_claves:
            self._claves.popitem(last=False)
        return None


# Instancia global; las pruebas la reinician en tests/conftest.py
contador = ContadorPeticiones()


def _clasificar(metodo: str, ruta: str) -> Clase:
    if metodo in _METODOS_LECTURA:
        return "lectura"
    return "sensible" if ruta.rstrip("/").endswith(_SUFIJOS_SENSIBLES) else "escritura"


def _ip(scope: Scope) -> str:
    """IP que entrega uvicorn. Si no es válida, no se usa como clave ni va al log."""
    cliente = scope.get("client")
    try:
        return str(ipaddress.ip_address(cliente[0])) if cliente else "desconocida"
    except ValueError:
        return "desconocida"


class LimitePeticionesMiddleware:
    """Responde 429 en las rutas /api/ que pasan su límite por minuto."""

    def __init__(
        self,
        app: ASGIApp,
        lectura: int,
        escritura: int,
        sensible: int,
        contador_peticiones: ContadorPeticiones = contador,
    ) -> None:
        self._app = app
        self._limites: dict[Clase, int] = {
            "lectura": lectura,
            "escritura": escritura,
            "sensible": sensible,
        }
        self._contador = contador_peticiones

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith("/api/"):
            await self._app(scope, receive, send)
            return

        clase = _clasificar(scope["method"], scope["path"])
        ip = _ip(scope)
        espera = self._contador.registrar((ip, clase), self._limites[clase])
        if espera is None:
            await self._app(scope, receive, send)
            return

        logger.warning("limite de peticiones excedido clase=%s ip=%s", clase, ip)
        respuesta = respuesta_problema(
            scope,
            429,
            "DEMASIADAS_SOLICITUDES",
            "Demasiadas solicitudes. Intente más tarde.",
            headers={"Retry-After": str(math.ceil(espera))},
        )
        await respuesta(scope, receive, send)
