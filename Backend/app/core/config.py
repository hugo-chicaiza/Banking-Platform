from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: Literal["development", "staging", "production"] = "development"
    app_name: str = "banking-platform-backend"
    log_level: str = "INFO"
    # Puerto no estándar; local solo en loopback. En Azure: APP_HOST=0.0.0.0 y WEBSITES_PORT=APP_PORT
    app_host: str = "127.0.0.1"
    app_port: int = 8471

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
