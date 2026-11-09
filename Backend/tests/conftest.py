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


@pytest.fixture(autouse=True)
def _sin_sobres_de_pin(monkeypatch):
    """Sin almacén de sobres de PIN salvo que la prueba instale uno: ninguna prueba
    escribe en disco ni conecta a MongoDB por la configuración local (.env).
    """
    from app.modules.tarjetas import sobre_pin

    monkeypatch.setattr(sobre_pin, "obtener_servicio", lambda: None)
