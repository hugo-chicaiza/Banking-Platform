import pytest

from app.modules.auth import agencias


@pytest.fixture(autouse=True)
def _agencia_matriz_de_prueba(monkeypatch):
    monkeypatch.setattr(agencias, "es_matriz_activa", lambda agencia: agencia == "001")
