import pytest

from app.core.api.rate_limit import contador
from app.core.config.settings import get_settings
from app.core.security import audit


@pytest.fixture(autouse=True)
def _auth_de_apis_activa(monkeypatch):
    """Las pruebas validan el auth que se va a reactivar (AUTH_APIS_ACTIVA=true).

    El modo apagado se prueba aparte en test_auth_interruptor.py.
    """
    monkeypatch.setenv("AUTH_APIS_ACTIVA", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _limite_de_peticiones_limpio():
    """El contador es global, así que se limpia entre pruebas."""
    contador.reiniciar()


@pytest.fixture(autouse=True)
def eventos_auditados(monkeypatch) -> list[audit.EventoAuditoria]:
    """Evita escribir auditoría real; los eventos quedan en esta lista."""
    eventos: list[audit.EventoAuditoria] = []
    monkeypatch.setattr(audit, "_persistir", eventos.append)
    return eventos
