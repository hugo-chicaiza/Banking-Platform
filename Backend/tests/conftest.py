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


@pytest.fixture(autouse=True)
def _sin_workos_real_en_seguridad(monkeypatch):
    """Seguridad (permisos de roles) nunca llama al WorkOS real configurado en .env:
    sin un falso instalado por la prueba, WorkOS responde como caído (503)."""
    import httpx

    from app.modules.seguridad import service

    def caido():
        raise httpx.ConnectError("WorkOS no disponible en pruebas")

    monkeypatch.setattr(service, "get_workos", caido)
