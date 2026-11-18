"""El adaptador de pendientes no omite controles ni altera operaciones funcionales."""

import inspect

import pytest
from fastapi import HTTPException

from app.core.api.errors import problema
from app.modules.parametros.funciones import funcion_pendiente


@pytest.mark.parametrize("status", [401, 403, 404, 409, 422, 503])
def test_conserva_error_previo_y_su_identidad(status):
    original = problema(status, "CONTROL_PREVIO", "Control existente")

    @funcion_pendiente
    def handler():
        raise original

    with pytest.raises(HTTPException) as resultado:
        handler()
    assert resultado.value is original


def test_solo_501_se_traduce_a_funcion_no_disponible():
    @funcion_pendiente
    def handler(id_: int) -> None:
        raise problema(501, "OPERACION_NO_HABILITADA", "Pendiente")

    with pytest.raises(HTTPException, match="FUNCION_NO_DISPONIBLE") as error:
        handler(1)
    assert error.value.status_code == 404
    assert str(inspect.signature(handler)) == "(id_: int) -> None"


def test_resultado_funcional_se_conserva():
    @funcion_pendiente
    def handler(valor: int) -> int:
        return valor + 1

    assert handler(5) == 6
