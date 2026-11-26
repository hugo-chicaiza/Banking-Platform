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
def _sin_reputacion_real(monkeypatch):
    """El análisis de archivos nunca consulta VirusTotal por la VIRUSTOTAL_API_KEY de
    .env: solo reglas locales, salvo que la prueba instale su clave y un httpx falso."""
    from app.core.documentos import analisis

    monkeypatch.setattr(analisis, "_clave_reputacion", lambda: "")


@pytest.fixture(autouse=True)
def _sin_workos_real_en_seguridad(monkeypatch):
    """Seguridad (permisos de roles) nunca llama al WorkOS real configurado en .env:
    sin un falso instalado por la prueba, WorkOS responde como caído (503)."""
    import httpx

    from app.modules.seguridad import service

    def caido():
        raise httpx.ConnectError("WorkOS no disponible en pruebas")

    monkeypatch.setattr(service, "get_workos", caido)


@pytest.fixture(autouse=True)
def _sin_integraciones_reales_en_aprobaciones(monkeypatch):
    import httpx
    from sqlalchemy.exc import SQLAlchemyError

    from app.modules.aprobaciones import identidad, scheduler
    from app.modules.parametros import funciones

    def caido():
        raise httpx.ConnectError("WorkOS real no permitido en suites controladas")

    def sin_conexion_implicita():
        raise SQLAlchemyError(
            "La lectura de banderas debe instalar su conexion de prueba explicita"
        )

    async def sin_tareas():
        return

    monkeypatch.setattr(identidad, "get_workos", caido)
    monkeypatch.setattr(scheduler, "ciclo", sin_tareas)
    monkeypatch.setattr(funciones, "cooperativa", sin_conexion_implicita)
