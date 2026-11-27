"""Alta y relevo directo del tutor de un menor existente (#387)."""

from datetime import date, datetime, timedelta
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
from app.modules.clientes.schemas import ClienteCreate
from app.modules.clientes.visibilidad import ficha_completa
from app.modules.parametros.service import hoy


def _requiere_ficha_completa(
    usuario: Annotated[Usuario, Depends(require_auth)],
) -> None:
    if not ficha_completa(usuario):
        raise problema(403, "SIN_PERMISO", "Se requiere acceso a la ficha completa.")


router = APIRouter(
    route_class=ProblemDetailsRoute, dependencies=[Depends(_requiere_ficha_completa)]
)
lectura = [Depends(require_roles("ADMIN", "ASESOR", "SUPERVISOR"))]
edicion = [Depends(require_roles("ADMIN", "ASESOR"))]
Db = Annotated[Connection, Depends(cooperativa)]


class AltaTutor(CamelModel):
    id_cliente_relacionado: int = Field(gt=0)
    fecha_efectiva: date
    tipo_respaldo: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)
    ]
    referencia_respaldo: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=250)
    ]


class RelevoTutor(AltaTutor):
    id_relacion_anterior: int = Field(gt=0)


class ClienteAlta(ClienteCreate):
    tutor: AltaTutor | None = None


class RequisitosAlta(CamelModel):
    edad_mayoria: int
    fecha_actual: date


class Tutor(CamelModel):
    id_relacion: int
    nombre: str
    fecha_inicio: date
    fecha_fin: date | None
    tipo_respaldo_alta: str | None
    respaldo_alta: str | None
    tipo_respaldo_fin: str | None
    respaldo_fin: str | None
    creado_por: int | None
    fecha_creacion: datetime
    finalizado_por: int | None
    finalizado_en: datetime | None


class HistorialTutor(CamelModel):
    admite_tutor: bool
    id_vigente: int | None
    historial: list[Tutor]


def _titular(
    conn: Connection,
    cliente: int,
    hoy_ecuador: date,
    fecha_efectiva: date | None = None,
) -> bool:
    sql = (
        "SELECT Estado,TipoCliente,FechaNacimiento FROM Clientes.Cliente "
        "WITH (UPDLOCK,HOLDLOCK) WHERE IdCliente=:id"
        if fecha_efectiva is not None
        else "SELECT Estado,TipoCliente,FechaNacimiento FROM Clientes.Cliente WHERE IdCliente=:id"
    )
    fila = conn.execute(text(sql), {"id": cliente}).first()
    if fila is None:
        raise problema(404, "CLIENTE_NO_ENCONTRADO", "No se encontró el cliente.")
    if (
        fecha_efectiva is not None
        and fila.FechaNacimiento
        and fecha_efectiva < fila.FechaNacimiento
    ):
        raise problema(
            422,
            "FECHA_INVALIDA",
            "La fecha efectiva es anterior al nacimiento del menor.",
        )
    return (
        fila.Estado != "Eliminado"
        and fila.TipoCliente == "Natural"
        and fila.FechaNacimiento is not None
        and edad_en(fila.FechaNacimiento, hoy_ecuador) < edad_mayoria(conn, hoy_ecuador)
    )


@router.get("/{idCliente}/relaciones/tutor", dependencies=lectura)
def listar(idCliente: int, conn: Db) -> HistorialTutor:
    fecha = hoy()
    admite = _titular(conn, idCliente, fecha)
    filas = conn.execute(
        text("""
        SELECT r.IdRelacion AS id_relacion, CONCAT(c.Nombres,' ',c.Apellidos) AS nombre,
            r.FechaInicio AS fecha_inicio, r.FechaFin AS fecha_fin,
            r.TipoRespaldoAlta AS tipo_respaldo_alta, r.RespaldoAlta AS respaldo_alta,
            r.TipoRespaldoFin AS tipo_respaldo_fin, r.RespaldoFin AS respaldo_fin,
            r.CreadoPor AS creado_por, r.FechaCreacion AS fecha_creacion,
            r.FinalizadoPor AS finalizado_por, r.FinalizadoEn AS finalizado_en
        FROM Clientes.ClienteRelacion AS r
        JOIN Clientes.Cliente AS c ON c.IdCliente=r.IdClienteRelacionado
        WHERE r.IdCliente=:id AND r.TipoRelacion='Tutor'
        ORDER BY r.FechaInicio DESC, r.IdRelacion DESC
        """),
        {"id": idCliente},
    ).mappings()
    historial = [Tutor.model_validate(fila) for fila in filas]
    vigentes = [
        tutor.id_relacion
        for tutor in historial
        if tutor.fecha_inicio <= fecha
        and (tutor.fecha_fin is None or tutor.fecha_fin >= fecha)
    ]
    if len(vigentes) > 1:
        raise problema(
            409, "RELACION_AMBIGUA", "Revisa el historial de tutores solapados."
        )
    return HistorialTutor(
        admite_tutor=admite, id_vigente=next(iter(vigentes), None), historial=historial
    )


def _validar_persona(
    conn: Connection, titular: int, datos: AltaTutor, fecha: date
) -> None:
    if datos.fecha_efectiva > fecha:
        raise problema(
            422,
            "FECHA_FUTURA",
            "Registra el cambio a partir de la fecha efectiva del documento.",
        )
    if datos.id_cliente_relacionado == titular:
        raise problema(422, "RELACIONADO_INVALIDO", "El tutor debe ser otra persona.")
    nacimiento = conn.execute(
        text("""
        SELECT FechaNacimiento FROM Clientes.Cliente WITH (HOLDLOCK)
        WHERE IdCliente=:persona AND TipoCliente='Natural' AND Estado='Activo'
        """),
        {"persona": datos.id_cliente_relacionado},
    ).scalar_one_or_none()
    if nacimiento is None or edad_en(nacimiento, datos.fecha_efectiva) < edad_mayoria(
        conn, datos.fecha_efectiva
    ):
        raise problema(
            422, "RELACIONADO_INVALIDO", "Elige una persona natural, adulta y activa."
        )


def insertar_tutor(conn: Connection, titular: int, datos: AltaTutor, actor: int) -> int:
    return conn.execute(
        text("""
            INSERT Clientes.ClienteRelacion
                (IdCliente,IdClienteRelacionado,TipoRelacion,FechaInicio,
                 TipoRespaldoAlta,RespaldoAlta,CreadoPor)
            OUTPUT inserted.IdRelacion
            VALUES (:id,:persona,'Tutor',:inicio,:tipo,:referencia,:actor)
        """),
        {
            "id": titular,
            "persona": datos.id_cliente_relacionado,
            "inicio": datos.fecha_efectiva,
            "tipo": datos.tipo_respaldo,
            "referencia": datos.referencia_respaldo,
            "actor": actor,
        },
    ).scalar_one()


def registrar_tutor_inicial(
    conn: Connection, titular: int, datos: AltaTutor, actor: int, fecha: date
) -> int:
    """La ficha es nueva. El llamador conserva la transacción de su alta."""
    if not _titular(conn, titular, fecha, datos.fecha_efectiva):
        raise problema(
            422, "TUTOR_NO_APLICA", "El tutor se registra en la ficha de un menor."
        )
    _validar_persona(conn, titular, datos, fecha)
    return insertar_tutor(conn, titular, datos, actor)


def _guardar(
    conn: Connection,
    titular: int,
    datos: AltaTutor,
    actor: int,
    anterior: int | None,
) -> int:
    fecha = hoy()
    with conn.begin():
        # El bloqueo de la ficha serializa el alta y el relevo para este menor.
        if not _titular(conn, titular, fecha, datos.fecha_efectiva):
            raise problema(
                422, "TUTOR_NO_APLICA", "El tutor se registra en la ficha de un menor."
            )
        _validar_persona(conn, titular, datos, fecha)
        valores = {
            "id": titular,
            "persona": datos.id_cliente_relacionado,
            "inicio": datos.fecha_efectiva,
            "tipo": datos.tipo_respaldo,
            "referencia": datos.referencia_respaldo,
            "actor": actor,
            "anterior": anterior,
        }
        cruces = conn.execute(
            text("""
            SELECT IdRelacion, IdClienteRelacionado, FechaInicio, FechaFin
            FROM Clientes.ClienteRelacion WITH (UPDLOCK,HOLDLOCK)
            WHERE IdCliente=:id AND TipoRelacion='Tutor'
              AND (FechaFin IS NULL OR FechaFin>=:inicio)
            """),
            valores,
        ).all()
        if anterior is None and cruces:
            raise problema(
                409,
                "TUTOR_YA_REGISTRADO",
                "El período ya tiene tutor. Revisa el historial.",
            )
        if anterior is not None:
            if (
                len(cruces) != 1
                or cruces[0].IdRelacion != anterior
                or cruces[0].FechaFin is not None
            ):
                raise problema(
                    409,
                    "TUTOR_CAMBIO",
                    "El tutor o su historial cambió. Vuelve a consultar.",
                )
            vigente = cruces[0]
            if vigente.IdClienteRelacionado == datos.id_cliente_relacionado:
                raise problema(
                    422, "RELACIONADO_INVALIDO", "Selecciona a un tutor diferente."
                )
            if vigente.FechaInicio >= datos.fecha_efectiva:
                raise problema(
                    422,
                    "FECHA_INVALIDA",
                    "El relevo debe ser posterior al inicio del tutor anterior.",
                )
            conn.execute(
                text("""
                UPDATE Clientes.ClienteRelacion SET FechaFin=:fin,
                    TipoRespaldoFin=:tipo, RespaldoFin=:referencia,
                    FinalizadoPor=:actor, FinalizadoEn=SYSUTCDATETIME()
                WHERE IdRelacion=:anterior
                """),
                {**valores, "fin": datos.fecha_efectiva - timedelta(days=1)},
            )
        return insertar_tutor(conn, titular, datos, actor)


def auditar_tutor(accion: str, relacion: int, actor: int, direccion_ip: str) -> None:
    audit.registrar(
        audit.EventoAuditoria(
            accion=accion,
            tabla="Clientes.ClienteRelacion",
            id_registro=str(relacion),
            resultado="Exitoso",
            usuario=actor,
            ip=direccion_ip,
            descripcion="Actualización del tutor del menor.",
        )
    )


@router.post("/{idCliente}/relaciones/tutor", dependencies=edicion, status_code=201)
def alta(
    idCliente: int,
    datos: AltaTutor,
    conn: Db,
    actor: UsuarioAuditoria,
    request: Request,
) -> int:
    relacion = _guardar(conn, idCliente, datos, actor, None)
    auditar_tutor("CLI_RELACION_INICIADA", relacion, actor, ip_cliente(request.scope))
    return relacion


@router.post(
    "/{idCliente}/relaciones/tutor/relevo", dependencies=edicion, status_code=201
)
def relevo(
    idCliente: int,
    datos: RelevoTutor,
    conn: Db,
    actor: UsuarioAuditoria,
    request: Request,
) -> int:
    anterior = datos.id_relacion_anterior
    relacion = _guardar(conn, idCliente, datos, actor, anterior)
    direccion_ip = ip_cliente(request.scope)
    auditar_tutor("CLI_RELACION_TERMINADA", anterior, actor, direccion_ip)
    auditar_tutor("CLI_RELACION_INICIADA", relacion, actor, direccion_ip)
    return relacion
