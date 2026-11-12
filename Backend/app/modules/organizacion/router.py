from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request, Response
from sqlalchemy import Connection

from app.core.api.errors import RESPUESTAS_ERROR, ProblemDetailsRoute, solo_parametros
from app.core.api.middleware import ip_cliente
from app.core.database.db import cooperativa
from app.core.security.auth import Usuario, require_auth, require_roles
from app.core.security.operador import auditar
from app.modules.organizacion import service
from app.modules.organizacion.schemas import AgenciaEstado, AgenciaEstadoUpdate


def _sin_cache(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"


router = APIRouter(
    prefix="/agencias",
    tags=["Organización"],
    route_class=ProblemDetailsRoute,
    responses=RESPUESTAS_ERROR,
    dependencies=[Depends(require_auth), Depends(_sin_cache)],
)
Db = Annotated[Connection, Depends(cooperativa)]


@router.patch(
    "/{id_agencia}/estado",
    response_model=AgenciaEstado,
    operation_id="AgenciaCambiarEstado",
    openapi_extra={"x-roles": ["ADMIN"]},
    dependencies=[Depends(solo_parametros())],
)
def cambiar_estado(
    id_agencia: Annotated[str, Path(min_length=3, max_length=3)],
    datos: AgenciaEstadoUpdate,
    conn: Db,
    request: Request,
    usuario: Annotated[Usuario, Depends(require_roles("ADMIN"))],
):
    resultado, anterior = service.cambiar_estado(conn, id_agencia, datos.estado)
    # Un replay no repite UPDATE ni genera una segunda escritura de auditoría.
    # Registrar solo cambios confirmados, con el mecanismo best-effort existente.
    if anterior != resultado.estado:
        with auditar(
            "CAMBIAR_ESTADO_AGENCIA",
            "Organizacion.Agencia",
            usuario,
            ip_cliente(request.scope),
            f"estado_anterior={anterior} estado_nuevo={resultado.estado}",
            id_agencia,
        ):
            pass
    return resultado
