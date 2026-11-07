from functools import lru_cache
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Única excepción a HTTPS: el FE y el callback locales (Vite) en la máquina del dev
_HOSTS_LOCALES = {"localhost", "127.0.0.1", "::1"}


def _exigir_https(nombre: str, valor: str) -> None:
    partes = urlsplit(valor)
    if partes.scheme == "https" or (
        partes.scheme == "http" and partes.hostname in _HOSTS_LOCALES
    ):
        return
    raise ValueError(f"{nombre} debe usar https:// (http:// solo para localhost)")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: Literal["development", "staging", "production"] = "production"
    app_name: str = "banking-platform-backend"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    # Puerto no estándar; local solo en loopback. En Azure: APP_HOST=0.0.0.0 y WEBSITES_PORT=APP_PORT
    app_host: str = "127.0.0.1"
    app_port: int = 8471
    # Por minuto y por IP. Mientras no se configure el proxy en Azure, todos llegan con
    # la misma IP y comparten el límite.
    limite_peticiones_activo: bool = True
    limite_lectura_por_minuto: int = 300
    limite_escritura_por_minuto: int = 60
    limite_sensible_por_minuto: int = 5

    db_driver: str = "ODBC Driver 18 for SQL Server"
    db_port: int = 1433
    db_encrypt: str = "yes"
    db_trust_server_certificate: str = "no"
    db_connection_timeout: int = 30
    db_auth_mode: Literal["sql", "managed_identity"] = "sql"
    azure_client_id: str = ""

    cooperativa_db_server: str = ""
    cooperativa_db_name: str = "CooperativaDB"
    cooperativa_db_user: str = ""
    cooperativa_db_password: SecretStr = SecretStr("")

    seguridad_db_server: str = ""
    seguridad_db_name: str = "SeguridadDB"
    seguridad_db_user: str = ""
    seguridad_db_password: SecretStr = SecretStr("")

    atm_hsm_aes_key_hex: str = ""
    atm_hsm_pin_generation_key_hex: str = ""
    atm_hsm_key_reference: str = "TEST-KEY-01"

    hsm_sim_clave_pan: SecretStr = SecretStr("")
    hsm_sim_clave_pvk: SecretStr = SecretStr("")
    hsm_sim_claves_pin_block: dict[str, SecretStr] = {}
    hsm_sim_referencia_pin_block: str = "TEST-KEY-01"

    # WorkOS AuthKit (F-03), patrón BFF: el navegador solo recibe una cookie cifrada
    workos_api_key: SecretStr = SecretStr("")
    workos_client_id: str = ""
    # Clave Fernet con la que se cifra la cookie de sesión
    workos_cookie_password: SecretStr = SecretStr("")
    # URL de GET /api/v1/auth/callback tal como la ve el navegador
    workos_redirect_uri: str = ""
    # Origen del FE (esquema://host[:puerto], sin ruta): redirecciones y control CSRF
    frontend_url: str = ""
    # Vínculos administrados por despliegue, nunca por el navegador ni por email.
    workos_audit_user_ids: dict[
        str, Annotated[int, Field(strict=True, ge=1, le=2147483647)]
    ] = Field(default_factory=dict)

    @field_validator("workos_audit_user_ids")
    @classmethod
    def _vinculos_auditoria(cls, valor: dict[str, int]) -> dict[str, int]:
        if any(not clave.startswith("user_") or len(clave) <= 5 for clave in valor):
            raise ValueError("Cada vínculo debe identificar un usuario WorkOS user_…")
        if len(set(valor.values())) != len(valor):
            raise ValueError(
                "Cada usuario de auditoría debe tener un único vínculo WorkOS"
            )
        return valor

    @field_validator("frontend_url")
    @classmethod
    def _solo_origen(cls, valor: str) -> str:
        valor = valor.rstrip("/")
        partes = urlsplit(valor)
        if valor and (
            partes.scheme not in ("http", "https")
            or not partes.netloc
            or partes.path
            or partes.query
        ):
            raise ValueError("FRONTEND_URL debe ser solo esquema://host[:puerto]")
        if valor:
            _exigir_https("FRONTEND_URL", valor)
        return valor

    @field_validator("workos_redirect_uri")
    @classmethod
    def _callback_https(cls, valor: str) -> str:
        if valor:
            if not urlsplit(valor).netloc:
                raise ValueError("WORKOS_REDIRECT_URI debe ser una URL completa")
            _exigir_https("WORKOS_REDIRECT_URI", valor)
        return valor

    def odbc_connection_string(self, db: Literal["cooperativa", "seguridad"]) -> str:
        server = getattr(self, f"{db}_db_server")
        parts = [
            f"DRIVER={{{self.db_driver}}}",
            f"SERVER=tcp:{server},{self.db_port}",
            f"DATABASE={getattr(self, f'{db}_db_name')}",
            f"Encrypt={self.db_encrypt}",
            f"TrustServerCertificate={self.db_trust_server_certificate}",
            f"Connection Timeout={self.db_connection_timeout}",
        ]
        if self.db_auth_mode == "managed_identity":
            parts.append("Authentication=ActiveDirectoryMsi")
            if self.azure_client_id:
                parts.append(f"UID={self.azure_client_id}")
        else:
            password = getattr(self, f"{db}_db_password").get_secret_value()
            parts += [f"UID={getattr(self, f'{db}_db_user')}", f"PWD={password}"]
        return ";".join(parts)


@lru_cache
def get_settings() -> Settings:
    return Settings()
