"""Política institucional explícita para los perfiles reconocidos por el backend."""

from collections.abc import Sequence
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.core.api.errors import problema
from app.core.config.settings import get_settings
from app.core.security.auth import ROLES, Rol


class PoliticaRoles(BaseModel):
    model_config = ConfigDict(extra="forbid")

    niveles: dict[Rol, Annotated[int, Field(strict=True, ge=1)]]
    privilegiados: set[Rol]
    incompatibles: list[tuple[Rol, Rol]]

    @model_validator(mode="after")
    def politica_completa(self) -> "PoliticaRoles":
        faltantes = set(ROLES) - set(self.niveles)
        if faltantes - {"CUMPLIMIENTO"}:
            raise ValueError("La jerarquía debe cubrir todos los roles vigentes.")
        if self.privilegiados.intersection(faltantes) or any(
            set(par).intersection(faltantes) for par in self.incompatibles
        ):
            raise ValueError("La política menciona un rol sin nivel configurado.")
        pares = {frozenset(par) for par in self.incompatibles}
        if len(pares) != len(self.incompatibles) or any(len(par) != 2 for par in pares):
            raise ValueError("Cada incompatibilidad debe unir dos roles distintos.")
        return self

    def requiere_aprobacion(
        self, actor: Sequence[str], actuales: Sequence[str], nuevos: Sequence[str]
    ) -> bool:
        anteriores, propuestos = set(actuales), set(nuevos)
        if (anteriores | propuestos).difference(self.niveles):
            raise problema(
                409, "ROLES_DESINCRONIZADOS", "Revise los roles del usuario."
            )
        nivel = max(
            (valor for rol, valor in self.niveles.items() if rol in actor), default=0
        )
        # Protege además la edición de un objetivo que ya tiene un nivel superior.
        if any(
            valor > nivel
            for rol, valor in self.niveles.items()
            if rol in anteriores or rol in propuestos
        ):
            raise problema(
                422, "NIVEL_INSUFICIENTE", "El nivel del actor es insuficiente."
            )
        if any(a in propuestos and b in propuestos for a, b in self.incompatibles):
            raise problema(422, "ROLES_INCOMPATIBLES", "Los roles son incompatibles.")
        return bool(self.privilegiados & (propuestos - anteriores))


def vigente() -> PoliticaRoles:
    try:
        return PoliticaRoles.model_validate_json(
            get_settings().e104_politica_roles or ""
        )
    except ValidationError:
        raise problema(
            503,
            "POLITICA_ROLES_NO_CONFIGURADA",
            "La política de roles no está disponible.",
        ) from None
