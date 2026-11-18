"""La bandera solo se consulta al alcanzar una rama pendiente."""

from unittest.mock import MagicMock, Mock

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError

from app.core.api.errors import problema
from app.modules.parametros import funciones
from app.modules.parametros.funciones import funcion_pendiente


@pytest.mark.parametrize("status", [401, 403, 404, 409, 422, 503])
def test_conserva_error_previo_y_su_identidad(status, monkeypatch):
    verificar = Mock()
    monkeypatch.setattr(funciones, "requiere_funcion", verificar)
    original = problema(status, "CONTROL_PREVIO", "Control existente")
    with pytest.raises(HTTPException) as resultado, funcion_pendiente("FUNCION_QA"):
        raise original
    assert resultado.value is original
    verificar.assert_not_called()


@pytest.mark.parametrize(
    "estado",
    [None, problema(404, "FUNCION_NO_DISPONIBLE", "Apagada"), SQLAlchemyError()],
)
def test_rama_pendiente_sigue_cerrada_aunque_la_bandera_este_activa(
    estado, monkeypatch
):
    verificar = Mock(side_effect=estado)
    fabrica = Mock(return_value=verificar)
    monkeypatch.setattr(funciones, "requiere_funcion", fabrica)
    conn, usuario = MagicMock(), MagicMock()
    with (
        pytest.raises(HTTPException, match="FUNCION_NO_DISPONIBLE") as resultado,
        funcion_pendiente("FUNCION_QA", conn, usuario),
    ):
        raise problema(501, "OPERACION_NO_HABILITADA", "Pendiente")
    assert resultado.value.status_code == 404
    fabrica.assert_called_once_with("FUNCION_QA")
    verificar.assert_called_once_with(conn, usuario)


def test_resultado_funcional_no_consulta_bandera(monkeypatch):
    verificar = Mock()
    monkeypatch.setattr(funciones, "requiere_funcion", verificar)
    with funcion_pendiente("FUNCION_QA"):
        resultado = 5 + 1
    assert resultado == 6
    verificar.assert_not_called()
