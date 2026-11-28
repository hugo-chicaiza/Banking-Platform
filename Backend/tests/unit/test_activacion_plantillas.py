from datetime import date
from unittest.mock import Mock

from sqlalchemy import Connection

from app.modules.contabilidad import repository
from app.modules.productos.activacion import _plantillas


def test_ahorro_informa_la_plantilla_de_deposito_faltante(monkeypatch):
    conn = Mock(spec=Connection)
    fecha = date(2026, 11, 23)
    buscar = Mock(return_value=None)
    monkeypatch.setattr(repository, "obtener_plantilla", buscar)

    assert _plantillas(conn, "CUENTA_AHORRO", fecha) == (
        "PLANTILLAS",
        False,
        "Sin vigencia: CAJA_DEPOSITO.",
    )
    buscar.assert_called_once_with(conn, "CAJA_DEPOSITO", fecha)


def test_plantilla_vigente_no_da_por_validada_una_matriz_incompleta(monkeypatch):
    monkeypatch.setattr(
        repository, "obtener_plantilla", Mock(return_value={"IdPlantillaAsiento": 1})
    )

    assert (
        _plantillas(Mock(spec=Connection), "CUENTA_AHORRO", date(2026, 11, 23))[1]
        is None
    )


def test_credito_informa_desembolso_sin_vigencia(monkeypatch):
    conn = Mock(spec=Connection)
    fecha = date(2026, 11, 29)
    buscar = Mock(return_value=None)
    monkeypatch.setattr(repository, "obtener_plantilla", buscar)

    assert _plantillas(conn, "CREDITO", fecha) == (
        "PLANTILLAS",
        False,
        "Sin vigencia: CREDITO_DESEMBOLSO_CUENTA.",
    )
    buscar.assert_called_once_with(conn, "CREDITO_DESEMBOLSO_CUENTA", fecha)


def test_desembolso_vigente_no_certifica_toda_la_matriz_de_credito(monkeypatch):
    monkeypatch.setattr(
        repository, "obtener_plantilla", Mock(return_value={"IdPlantillaAsiento": 36})
    )

    assert _plantillas(Mock(spec=Connection), "CREDITO", date(2026, 11, 30))[1] is None
