from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import ConfigDict, StringConstraints, model_validator
from pydantic.json_schema import SkipJsonSchema

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


# --- AUT-05..09: usuarios internos (C-05) --------------------------------------------

Rol = Literal[
    "ADMIN",
    "ASESOR",
    "CAJERO",
    "SUPERVISOR",
    "APROBADOR_CREDITO",
    "CONTADOR",
    "AUDITOR",
]
EstadoUsuario = Literal["Activo", "Inactivo", "Bloqueado"]
EstadoInvitacion = Literal["pending", "accepted", "expired", "revoked"]

_Texto = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Nombre = Annotated[_Texto, StringConstraints(max_length=100)]
Email = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        to_lower=True,
        max_length=100,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
    ),
]
CodigoAgencia = Annotated[str, StringConstraints(pattern=r"^\d{3}$")]


class BloqueoVigente(CamelModel):
    motivo: str
    fecha_bloqueo: datetime
    observaciones: str | None


class UsuarioResumen(CamelModel):
    """Item de AUT-05. Nunca incluye IntentosFallidos."""

    id_usuario: int
    username: str
    nombres: str
    apellidos: str
    email: str
    # Rol de la membresía en EnquoCoop (copia en Organizacion.Usuarios.RolesWorkOS)
    rol: str | None
    estado: EstadoUsuario
    id_agencia: str | None
    # KeyUsuario no nulo: ya aceptó la invitación e inició sesión
    vinculado: bool
    fecha_creacion: datetime


class UsuarioDetalle(UsuarioResumen):
    """Detalle (AUT-07) y respuesta de AUT-06, AUT-08 y AUT-09."""

    cedula: str
    ultimo_acceso: datetime | None
    # Solo si no está vinculado; null si no se consultó o WorkOS no respondió
    estado_invitacion: EstadoInvitacion | None = None
    bloqueo: BloqueoVigente | None = None


class PageUsuario(CamelModel):
    items: list[UsuarioResumen]
    page: int
    page_size: int
    total: int


class UsuarioCreate(CamelModel):
    """AUT-06. La contraseña no viaja: la define el usuario al aceptar la invitación."""

    model_config = ConfigDict(extra="forbid")

    username: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True,
            min_length=3,
            max_length=50,
            pattern=r"^[A-Za-z0-9._-]+$",
        ),
    ]
    nombres: Nombre
    apellidos: Nombre
    email: Email
    cedula: Annotated[str, StringConstraints(pattern=r"^\d{10}$")]
    id_agencia: CodigoAgencia
    rol: Rol


class UsuarioUpdate(CamelModel):
    """AUT-08. Omitir conserva el valor. username y cedula no se editan."""

    model_config = ConfigDict(extra="forbid")

    nombres: Nombre | SkipJsonSchema[None] = None
    apellidos: Nombre | SkipJsonSchema[None] = None
    email: Email | SkipJsonSchema[None] = None
    estado: EstadoUsuario | SkipJsonSchema[None] = None
    # Seguridad.Bloqueos.MotivoBloqueo varchar(30): obligatorio al bloquear
    motivo: Annotated[_Texto, StringConstraints(max_length=30)] | None = None
    observaciones: Annotated[_Texto, StringConstraints(max_length=300)] | None = None
    id_agencia: CodigoAgencia | SkipJsonSchema[None] = None

    @model_validator(mode="after")
    def _coherente(self) -> Self:
        if self.estado == "Bloqueado" and not self.motivo:
            raise ValueError("motivo es obligatorio al bloquear.")
        if self.motivo is not None and self.estado != "Bloqueado":
            raise ValueError("motivo solo aplica al bloquear.")
        campos = (
            self.nombres,
            self.apellidos,
            self.email,
            self.estado,
            self.id_agencia,
        )
        if all(valor is None for valor in campos):
            raise ValueError("No hay cambios.")
        return self


class RolUpdate(CamelModel):
    """AUT-09: un solo rol por usuario."""

    model_config = ConfigDict(extra="forbid")

    rol: Rol
