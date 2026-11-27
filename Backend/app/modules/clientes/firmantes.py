"""Vínculos de firma en la ficha de Clientes (#387)."""

from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import Field, StringConstraints
from sqlalchemy import Connection, text

from app.core.api.errors import ProblemDetailsRoute, problema
from app.core.api.middleware import ip_cliente
from app.core.api.schemas import CamelModel
from app.core.database.db import cooperativa
from app.core.security import audit
from app.core.security.auth import (
    Usuario,
    UsuarioAuditoria,
    require_auth,
    require_roles,
)
from app.modules.clientes.relaciones import edad_en, edad_mayoria
from app.modules.clientes.visibilidad import ficha_completa
from app.modules.parametros.service import hoy

Texto = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=250)
]
Db = Annotated[Connection, Depends(cooperativa)]


def _requiere_ficha_completa(
    usuario: Annotated[Usuario, Depends(require_auth)],
) -> None:
    if not ficha_completa(usuario):
        raise problema(403, "SIN_PERMISO", "Se requiere acceso a la ficha completa.")


router = APIRouter(
    route_class=ProblemDetailsRoute, dependencies=[Depends(_requiere_ficha_completa)]
)
edicion = [Depends(require_roles("ADMIN", "ASESOR"))]


class AltaFirmante(CamelModel):
    id_cliente_relacionado: int = Field(gt=0)
    fecha_inicio: date
    alcance: Texto
    respaldo: Texto


class FinFirmante(CamelModel):
    fecha_fin: date
    respaldo: Texto


class Firmante(CamelModel):
    id_relacion: int
    id_cliente_relacionado: int
    nombre: str
    fecha_inicio: date
    fecha_fin: date | None
    alcance: str | None
    respaldo_alta: str | None
    respaldo_fin: str | None
    creado_por: int | None
    fecha_creacion: datetime
    finalizado_por: int | None
    finalizado_en: datetime | None


def _titular(conn: Connection, cliente: int, *, escritura: bool) -> None:
    sql = (
        "SELECT Estado FROM Clientes.Cliente WITH (UPDLOCK,HOLDLOCK) WHERE IdCliente=:id"
        if escritura
        else "SELECT Estado FROM Clientes.Cliente WHERE IdCliente=:id"
    )
    estado = conn.execute(text(sql), {"id": cliente}).scalar_one_or_none()
    if estado is None:
        raise problema(404, "CLIENTE_NO_ENCONTRADO", "No se encontró el cliente.")
    if escritura and estado == "Eliminado":
        raise problema(409, "CLIENTE_ELIMINADO", "Este cliente está eliminado.")


def _auditar(accion: str, relacion: int, actor: int, request: Request) -> None:
    audit.registrar(
        audit.EventoAuditoria(
            accion=accion,
            tabla="Clientes.ClienteRelacion",
            id_registro=str(relacion),
            resultado="Exitoso",
            usuario=actor,
            ip=ip_cliente(request.scope),
            descripcion="Actualización del vínculo de firma.",
        )
    )


@router.get(
    "/{idCliente}/relaciones/firmantes",
    dependencies=[Depends(require_roles("ASESOR", "SUPERVISOR", "ADMIN"))],
)
def listar(idCliente: int, conn: Db) -> list[Firmante]:
    _titular(conn, idCliente, escritura=False)
    filas = conn.execute(
        text("""
        SELECT r.IdRelacion AS id_relacion, r.IdClienteRelacionado AS id_cliente_relacionado,
          CONCAT(c.Nombres, ' ', c.Apellidos) AS nombre, r.FechaInicio AS fecha_inicio,
          CASE WHEN r.FinalizadoEn IS NULL THEN DATEADD(day,1,r.FechaFin) ELSE r.FechaFin END AS fecha_fin,
          r.AlcanceFirma AS alcance, r.RespaldoAlta AS respaldo_alta, r.RespaldoFin AS respaldo_fin,
          r.CreadoPor AS creado_por, r.FechaCreacion AS fecha_creacion,
          r.FinalizadoPor AS finalizado_por, r.FinalizadoEn AS finalizado_en
        FROM Clientes.ClienteRelacion r JOIN Clientes.Cliente c ON c.IdCliente=r.IdClienteRelacionado
        WHERE r.IdCliente=:id AND r.TipoRelacion='Firmante'
        ORDER BY r.FechaInicio DESC, r.IdRelacion DESC
    """),
        {"id": idCliente},
    ).mappings()
    return [Firmante.model_validate(fila) for fila in filas]


@router.post("/{idCliente}/relaciones/firmantes", dependencies=edicion, status_code=201)
def agregar(
    idCliente: int,
    datos: AltaFirmante,
    conn: Db,
    actor: UsuarioAuditoria,
    request: Request,
) -> int:
    if datos.fecha_inicio > hoy() or datos.id_cliente_relacionado == idCliente:
        raise problema(
            422, "RELACION_INVALIDA", "Revisa la persona y la fecha de inicio."
        )
    with conn.begin():
        _titular(conn, idCliente, escritura=True)
        nacimiento = conn.execute(
            text("""
            SELECT FechaNacimiento FROM Clientes.Cliente WITH (HOLDLOCK)
            WHERE IdCliente=:persona AND TipoCliente='Natural' AND Estado='Activo'
        """),
            {"persona": datos.id_cliente_relacionado},
        ).scalar_one_or_none()
        if nacimiento is None or edad_en(nacimiento, datos.fecha_inicio) < edad_mayoria(
            conn, datos.fecha_inicio
        ):
            raise problema(
                422,
                "RELACIONADO_INVALIDO",
                "Elige otra persona natural, adulta y activa.",
            )
        valores = {
            "id": idCliente,
            "persona": datos.id_cliente_relacionado,
            "inicio": datos.fecha_inicio,
            "alcance": datos.alcance,
            "respaldo": datos.respaldo,
            "actor": actor,
        }
        if conn.execute(
            text("""
            SELECT 1 FROM Clientes.ClienteRelacion WHERE IdCliente=:id AND IdClienteRelacionado=:persona
            AND TipoRelacion='Firmante' AND AlcanceFirma=:alcance AND (FechaFin IS NULL OR FechaFin>:inicio)
        """),
            valores,
        ).first():
            raise problema(
                409,
                "RELACION_DUPLICADA",
                "Ya existe un vínculo para esta persona, alcance y período.",
            )
        relacion = conn.execute(
            text("""
            INSERT Clientes.ClienteRelacion (IdCliente,IdClienteRelacionado,TipoRelacion,FechaInicio,
                AlcanceFirma,RespaldoAlta,CreadoPor)
            OUTPUT inserted.IdRelacion VALUES (:id,:persona,'Firmante',:inicio,:alcance,:respaldo,:actor)
        """),
            valores,
        ).scalar_one()
    _auditar("CLI_RELACION_INICIADA", relacion, actor, request)
    return relacion


@router.post(
    "/{idCliente}/relaciones/firmantes/{idRelacion}/fin",
    dependencies=edicion,
    status_code=204,
    response_model=None,
)
def finalizar(
    idCliente: int,
    idRelacion: int,
    datos: FinFirmante,
    conn: Db,
    actor: UsuarioAuditoria,
    request: Request,
) -> None:
    with conn.begin():
        _titular(conn, idCliente, escritura=True)
        fila = conn.execute(
            text("""
            SELECT FechaInicio, FechaFin, AlcanceFirma FROM Clientes.ClienteRelacion
            WHERE IdCliente=:id AND IdRelacion=:rel AND TipoRelacion='Firmante'
        """),
            {"id": idCliente, "rel": idRelacion},
        ).first()
        if fila is None:
            raise problema(
                404, "RELACION_NO_ENCONTRADA", "No se encontró este vínculo de firma."
            )
        if fila.FechaFin is not None:
            raise problema(
                409, "RELACION_FINALIZADA", "El vínculo ya tiene fecha de fin."
            )
        fin = datos.fecha_fin
        if fin < fila.FechaInicio or datos.fecha_fin > hoy():
            raise problema(
                422, "FECHA_INVALIDA", "Revisa la fecha desde la que deja de firmar."
            )
        conn.execute(
            text("""
            UPDATE Clientes.ClienteRelacion SET FechaFin=:fin, RespaldoFin=:respaldo,
                FinalizadoPor=:actor, FinalizadoEn=SYSUTCDATETIME() WHERE IdRelacion=:rel
        """),
            {"fin": fin, "respaldo": datos.respaldo, "actor": actor, "rel": idRelacion},
        )
    _auditar("CLI_RELACION_TERMINADA", idRelacion, actor, request)
