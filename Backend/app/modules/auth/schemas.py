from app.core.api.schemas import CamelModel


class UsuarioSesion(CamelModel):
    """Respuesta de GET /api/v1/auth/me (AUT-04)."""

    id_usuario: str
    nombre: str
    email: str
    id_organizacion: str | None
    roles: list[str]
    permisos: list[str]
    id_agencia: str | None


class LogoutResponse(CamelModel):
    """Respuesta de POST /api/v1/auth/logout (AUT-03).

    El FE debe navegar a esta URL: cierra la sesión del Hosted UI de AuthKit y vuelve a
    la pantalla de login. Si no había sesión, es directamente la de login.
    """

    logout_url: str
