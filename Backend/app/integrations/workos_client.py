"""Cliente de WorkOS AuthKit (F-03).

Usuarios, roles y sesiones se administran en WorkOS: el backend no guarda contraseñas
ni tokens. Es instanciado para usarse una vez y reutilizarse.
"""

from functools import lru_cache
from urllib.parse import urlsplit

from cryptography.fernet import Fernet
from workos import WorkOSClient

from app.core.config.settings import get_settings


@lru_cache
def get_workos() -> WorkOSClient:
    settings = get_settings()
    if not settings.workos_api_key.get_secret_value() or not settings.workos_client_id:
        raise RuntimeError(
            "Faltan WORKOS_API_KEY o WORKOS_CLIENT_ID en la configuración"
        )
    return WorkOSClient(
        api_key=settings.workos_api_key.get_secret_value(),
        client_id=settings.workos_client_id,
    )


@lru_cache
def get_cookie_password() -> str:
    """Clave que cifra la cookie de sesión. El SDK usa Fernet: 32 bytes en base64."""
    clave = get_settings().workos_cookie_password.get_secret_value()
    try:
        Fernet(clave)
    except ValueError:
        raise RuntimeError(
            "WORKOS_COOKIE_PASSWORD no es una clave Fernet válida. Genérala con: "
            'python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"'
        ) from None
    return clave


RUTA_CALLBACK = "/api/v1/auth/callback"


def get_frontend_urls() -> tuple[str, ...]:
    origenes = get_settings().origenes_frontend
    if not origenes:
        raise RuntimeError("Falta FRONTEND_URL en la configuración")
    return origenes


def get_frontend_url(host: str | None = None) -> str:
    """Origen del FE para una petición: el de FRONTEND_URL cuyo host coincide con el
    header Host; si ninguno coincide, el primero. Nunca devuelve un origen fuera de la
    lista, así que un Host falsificado no sirve para redirigir a otro sitio.
    """
    origenes = get_frontend_urls()
    if host:
        for origen in origenes:
            if urlsplit(origen).netloc.lower() == host.lower():
                return origen
    return origenes[0]


def get_redirect_uri(origen: str) -> str:
    """Callback que se envía a WorkOS; debe estar registrado en sus Redirects."""
    return get_settings().workos_redirect_uri or f"{origen}{RUTA_CALLBACK}"
