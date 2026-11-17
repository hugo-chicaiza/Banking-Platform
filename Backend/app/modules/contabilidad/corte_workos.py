"""Autoriza el corte E2-01 con las identidades de la sesión WorkOS."""

import json
from functools import lru_cache
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import URL, Engine, create_engine, text
from sqlalchemy.exc import DBAPIError

from app.core.api.errors import ProblemDetailsRoute, problema
from app.core.config.settings import get_settings
from app.core.database.db import get_engine
from app.core.database.procedimientos import ejecutar_con_salidas
from app.core.security.auth import Usuario, require_permiso

router = APIRouter(prefix="/cortes-e201", route_class=ProblemDetailsRoute)
Preparador = Annotated[
    Usuario, Depends(require_permiso("con-reclasificacion-preparar"))
]
Aprobador = Annotated[Usuario, Depends(require_permiso("con-reclasificacion-aprobar"))]


class Plan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    IdCorte: UUID
    FechaCorte: str = Field(min_length=10, max_length=35)
    NumeroAsiento: str = Field(min_length=1, max_length=20)
    IdFechaContable: int = Field(gt=0)
    IdAgencia: str = Field(min_length=3, max_length=3)
    Controles: list[dict[str, Any]] = Field(min_length=1, max_length=1000)
    ConciliacionAhorro: dict[str, Any]


class Aprobacion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hashPlan: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    comentario: str = Field(min_length=1, max_length=500)


@lru_cache
def motor_corte() -> Engine:
    cfg = get_settings()
    user = cfg.e201_servicio_sql_user.strip()
    if (
        not user
        or not cfg.e201_servicio_sql_password.get_secret_value()
        or user.casefold() in {cfg.cooperativa_db_user.casefold(), "devcat"}
    ):
        raise problema(
            503,
            "CORTE_NO_CONFIGURADO",
            "Falta el principal privado del servicio de corte.",
        )
    privada = cfg.model_copy(
        update={
            "db_auth_mode": "sql",
            "cooperativa_db_user": user,
            "cooperativa_db_password": cfg.e201_servicio_sql_password,
        }
    )
    url = URL.create(
        "mssql+pyodbc",
        query={"odbc_connect": privada.odbc_connection_string("cooperativa")},
    )
    return create_engine(url, pool_pre_ping=True, hide_parameters=True)


def identidad_vigente(sujeto: str) -> int:
    """El vínculo y el estado son autoritativos en SeguridadDB."""
    with get_engine("seguridad").connect() as conn:
        ids = (
            conn.execute(
                text("""
            SELECT TOP (2) UsuarioID FROM Organizacion.Usuarios
            WHERE KeyUsuario COLLATE Latin1_General_100_BIN2=:sujeto AND Estado='Activo'
        """),
                {"sujeto": sujeto},
            )
            .scalars()
            .all()
        )
    if len(ids) != 1:
        raise problema(
            403,
            "USUARIO_INTERNO_NO_VINCULADO",
            "Falta un vínculo institucional activo y único.",
        )
    return int(ids[0])


def operar(
    modo: str,
    usuario: Usuario,
    plan: UUID,
    contenido: str | None = None,
    hash_plan: bytes | None = None,
    comentario: str | None = None,
) -> dict[str, Any]:
    organizacion = get_settings().workos_organization_id
    if not organizacion or usuario.id_organizacion != organizacion:
        raise problema(
            403,
            "ORGANIZACION_NO_AUTORIZADA",
            "La sesión debe pertenecer a la institución.",
        )
    try:
        actor = identidad_vigente(usuario.id_usuario)
        with motor_corte().begin() as conn:
            sql = (
                "EXEC E201.usp_PlanWorkOS @Modo=?,@Actor=?,@Sujeto=?,@Organizacion=?,@IdPlan=?,"
                "@Contenido=?,@Hash=?,@Comentario=?"
            )
            base = (actor, usuario.id_usuario, organizacion, str(plan))
            if modo == "APROBAR":
                revision = ejecutar_con_salidas(
                    conn, sql, ("VER", *base, None, None, None)
                )
                if (
                    identidad_vigente(revision["SujetoPreparador"])
                    != revision["UsuarioPreparador"]
                ):
                    raise problema(
                        409,
                        "VINCULO_PREPARADOR_CAMBIO",
                        "El vínculo del preparador cambió.",
                    )
            resultado = ejecutar_con_salidas(
                conn, sql, (modo, *base, contenido, hash_plan, comentario)
            )
            resultado.pop("SujetoPreparador", None)
            resultado.pop("UsuarioPreparador", None)
            return resultado
    except DBAPIError as error:
        codigos = {
            56406: (404, "PLAN_NO_ENCONTRADO", "No existe ese plan de corte."),
            56411: (
                403,
                "PERMISO_CORTE_REQUERIDO",
                "Falta habilitación institucional o comentario.",
            ),
            56412: (403, "AUTOAPROBACION_PROHIBIDA", "Debe aprobar otra persona."),
            56413: (
                409,
                "PLAN_NO_APROBABLE",
                "El hash es incorrecto o el plan ya fue aprobado.",
            ),
            56407: (409, "OBJETIVO_CAMBIO", "El objetivo cambió desde la preparación."),
        }
        for numero, detalle in codigos.items():
            if f"({numero})" in str(error.orig):
                raise problema(*detalle) from None
        raise


@router.post("", status_code=201)
def preparar(datos: Plan, usuario: Preparador) -> dict[str, Any]:
    contenido = datos.model_dump(mode="json")
    contenido["Alcance"] = "EFECTIVO_AHORRO"
    return operar(
        "PREPARAR", usuario, uuid4(), json.dumps(contenido, ensure_ascii=False)
    )


@router.get("/{id_plan}")
def ver(id_plan: UUID, usuario: Aprobador) -> dict[str, Any]:
    return operar("VER", usuario, id_plan)


@router.post("/{id_plan}/aprobaciones")
def aprobar(id_plan: UUID, datos: Aprobacion, usuario: Aprobador) -> dict[str, Any]:
    return operar(
        "APROBAR",
        usuario,
        id_plan,
        hash_plan=bytes.fromhex(datos.hashPlan),
        comentario=datos.comentario,
    )
