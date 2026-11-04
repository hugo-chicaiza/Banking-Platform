"""Cliente de WorkOS AuthKit (F-03).

Usuarios, roles y sesiones se administran en WorkOS: el backend no guarda contraseñas
ni tokens. Es instanciado para usarse una vez y reutilizarse.
"""

from functools import lru_cache

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


def get_frontend_url() -> str:
    url = get_settings().frontend_url
    if not url:
        raise RuntimeError("Falta FRONTEND_URL en la configuración")
    return url


def get_redirect_uri() -> str:
    uri = get_settings().workos_redirect_uri
    if not uri:
        raise RuntimeError("Falta WORKOS_REDIRECT_URI en la configuración")
    return uri
