from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request, Response
from sqlalchemy import Connection

from app.core.api.errors import RESPUESTAS_ERROR, ProblemDetailsRoute, solo_parametros
from app.core.api.middleware import ip_cliente
from app.core.database.db import cooperativa
from app.core.security.auth import (
    Usuario,
    UsuarioAuditoria,
    require_auth,
    require_roles,
)
from app.core.security.operador import auditar
from app.modules.organizacion import service
from app.modules.organizacion.schemas import (
    AgenciaEstado,
    AgenciaEstadoUpdate,
    Entidad,
    EntidadUpdate,
)


def _sin_cache(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"


router = APIRouter(
    tags=["Organización"],
    route_class=ProblemDetailsRoute,
    responses=RESPUESTAS_ERROR,
    dependencies=[Depends(require_auth), Depends(_sin_cache)],
)
Db = Annotated[Connection, Depends(cooperativa)]


@router.patch(
    "/agencias/{id_agencia}/estado",
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


@router.get(
    "/organizacion/entidad",
    response_model=Entidad,
    operation_id="EntidadObtener",
    summary="Obtener la entidad",
    openapi_extra={"x-roles": ["ASESOR", "ADMIN"]},
    dependencies=[
        Depends(require_roles("ASESOR", "ADMIN")),
        Depends(solo_parametros()),
    ],
)
def obtener_entidad(conn: Db) -> Entidad:
    """Devuelve la entidad con IdEntidad = 1, incluso si está inactiva.

    Requiere sesión y rol ASESOR o ADMIN. Si falta el registro, responde
    404 ENTIDAD_NO_ENCONTRADA.
    """
    return service.obtener_entidad(conn)


@router.patch(
    "/organizacion/entidad",
    response_model=Entidad,
    operation_id="EntidadEditar",
    summary="Editar parcialmente la entidad",
    openapi_extra={"x-roles": ["ADMIN"]},
    dependencies=[Depends(solo_parametros())],
)
def editar_entidad(
    datos: EntidadUpdate,
    conn: Db,
    request: Request,
    modificado_por: UsuarioAuditoria,
    usuario: Annotated[Usuario, Depends(require_roles("ADMIN"))],
) -> Entidad:
    """Actualiza IdEntidad = 1 y devuelve todos sus datos persistidos.

    Requiere ADMIN. Envíe al menos un campo editable. Omitir un campo conserva
    su valor y null vacía los campos anulables. Los campos idEntidad,
    fechaRegistro y modificadoPor son administrados por el backend.
    ModificadoPor se obtiene de la sesión. Un cuerpo inválido responde
    400 DATOS_INVALIDOS. Una entidad inexistente responde
    404 ENTIDAD_NO_ENCONTRADA. Repetir los valores actuales devuelve 200
    sin otra escritura de auditoría. Los cambios efectivos se auditan
    después del commit mediante el mecanismo best-effort existente.
    """
    resultado, campos = service.editar_entidad(conn, datos, modificado_por)
    if campos:
        with auditar(
            "EDITAR_ENTIDAD",
            "Organizacion.Entidad",
            usuario,
            ip_cliente(request.scope),
            "campos=" + ",".join(campos),
            str(resultado.id_entidad),
        ):
            pass
    return resultado
