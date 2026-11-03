import pytest

from app.core.api.rate_limit import contador
from app.core.security import audit


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
