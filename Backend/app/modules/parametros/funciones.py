"""Contrato E0-09 para handlers sincronicos que aun declaran una funcion pendiente.

La ausencia de implementacion siempre falla cerrada, incluso si alguien enciende
una bandera. No se ejecuta una operacion alternativa ni se anticipa este control
a la autenticacion, autorizacion o validacion de datos de la ruta existente.
"""

from collections.abc import Callable
from functools import wraps
from typing import ParamSpec, TypeVar

from starlette.exceptions import HTTPException

from app.core.api.errors import problema

P = ParamSpec("P")
T = TypeVar("T")


def funcion_pendiente(funcion: Callable[P, T]) -> Callable[P, T]:
    @wraps(funcion)
    def ejecutar(*args: P.args, **kwargs: P.kwargs) -> T:
        try:
            return funcion(*args, **kwargs)
        except HTTPException as error:
            if error.status_code != 501:
                raise
            raise problema(
                404, "FUNCION_NO_DISPONIBLE", "La funcion no esta disponible."
            ) from None

    return ejecutar
