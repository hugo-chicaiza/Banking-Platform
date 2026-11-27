"""Consulta de la bitácora de auditoría (E8-01).

Rango de fechas obligatorio y acotado por AUD_RANGO_MAX_DIAS (ASVS 15.2.2). ADMIN y
AUDITOR ven todas las agencias; los demás roles, solo las suyas (los eventos sin agencia
tampoco). Los datos personales del cliente salen enmascarados de los cambios (ASVS 8.2.3);
el resto de antes/después se entrega completo, sin truncar.
"""

import json
import re
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import Connection

from app.core.api.errors import problema
from app.core.security.auth import Usuario
from app.modules.auditoria import repository as repo
from app.modules.auditoria.schemas import (
    Aprobacion,
    EventoDetalle,
    EventoItem,
    PageEventos,
    Persona,
    TipoEvento,
)
from app.modules.parametros import general

_ECUADOR = timezone(timedelta(hours=-5))
PARAMETRO_RANGO = "AUD_RANGO_MAX_DIAS"
_DATOS_PERSONALES = frozenset(
    {
        "nombre",
        "nombres",
        "apellido",
        "apellidos",
        "identificacion",
        "documento",
        "email",
        "correo",
        "telefono",
        "celular",
        "direccion",
        "direcciones",
        "calle",
        "referencia",
        "nacimiento",
    }
)


def _es_dato_personal(clave: str) -> bool:
    separado = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", clave).lower()
    return bool(set(re.split(r"[^a-z0-9]+", separado)) & _DATOS_PERSONALES)


def _ocultar(valor: Any) -> Any:
    if isinstance(valor, dict):
        return {k: _ocultar(v) for k, v in valor.items()}
    if isinstance(valor, list):
        return [_ocultar(v) for v in valor]
    if isinstance(valor, str) and valor and valor != "[filtrado]":
        return valor[0] + "*" * (len(valor) - 1)
    return valor


def enmascarar_cambios(cambios: Any) -> Any:
    """Oculta todo lo que cuelga de una clave de dato personal, a cualquier nivel."""
    if isinstance(cambios, dict):
        return {
            k: _ocultar(v) if _es_dato_personal(str(k)) else enmascarar_cambios(v)
            for k, v in cambios.items()
        }
    if isinstance(cambios, list):
        return [enmascarar_cambios(v) for v in cambios]
    return cambios


def alcance(usuario: Usuario) -> tuple[str, ...] | None:
    """None = todas las agencias."""
    if {"ADMIN", "AUDITOR"} & set(usuario.roles):
        return None
    return usuario.agencias_permitidas()


def validar_filtros(
    coop: Connection, filtros: dict[str, Any], usuario: Usuario
) -> None:
    desde: date | None = filtros.get("desde")
    hasta: date | None = filtros.get("hasta")
    if desde is None or hasta is None:
        raise problema(
            400, "RANGO_REQUERIDO", "Indique el rango de fechas (desde y hasta)."
        )
    if hasta < desde:
        raise problema(
            422, "RANGO_INVALIDO", "La fecha hasta no puede ser anterior a desde."
        )
    maximo = int(
        str(general.valor(coop, PARAMETRO_RANGO, datetime.now(_ECUADOR).date()))
    )
    if (hasta - desde).days + 1 > maximo:
        raise problema(
            422, "RANGO_EXCEDIDO", f"El rango no puede superar {maximo} días."
        )
    agencias = alcance(usuario)
    if (
        filtros.get("agencia")
        and agencias is not None
        and filtros["agencia"] not in agencias
    ):
        raise problema(
            403,
            "AGENCIA_NO_AUTORIZADA",
            "No tiene acceso a los eventos de esa agencia.",
        )


def _item(fila: dict[str, Any]) -> EventoItem:
    utc = fila["FechaHoraUTC"]
    if utc is None and fila["FechaHora"] is not None:
        utc = fila["FechaHora"] + timedelta(hours=5)  # formato anterior: hora local
    utc = utc.replace(tzinfo=UTC) if utc is not None and utc.tzinfo is None else utc
    return EventoItem(
        id=fila["AuditoriaID"],
        id_evento=str(fila["IdEvento"]) if fila["IdEvento"] else None,
        codigo_evento=fila["CodigoEvento"],
        modulo=fila["Modulo"],
        severidad=fila["Severidad"],
        fecha_hora_utc=utc,
        fecha_hora_local=utc.astimezone(_ECUADOR) if utc else None,
        usuario=fila["UsuarioID"],
        nombre_usuario=fila["NombreUsuario"],
        agencia=fila["IdAgencia"],
        canal=fila["Canal"],
        origen=fila["DireccionIP"],
        resultado=fila["Resultado"],
        tipo_objetivo=fila["TipoObjetivo"],
        id_objetivo=fila["IdObjetivo"],
        correlacion=fila["IdCorrelacion"],
        descripcion=fila["Descripcion"],
        formato_anterior=bool(fila["FormatoAnterior"]),
    )


def buscar(
    conn: Connection, coop: Connection, filtros: dict[str, Any], usuario: Usuario
) -> PageEventos:
    validar_filtros(coop, filtros, usuario)
    page, page_size = filtros["page"], filtros["page_size"]
    filas, total = repo.buscar_eventos(conn, filtros, alcance(usuario), page, page_size)
    return PageEventos(
        items=[_item(f) for f in filas], total=total, page=page, page_size=page_size
    )


def para_exportar(
    conn: Connection,
    coop: Connection,
    filtros: dict[str, Any],
    usuario: Usuario,
    max_filas: int,
) -> list[EventoItem]:
    """422 si el resultado pasa de `max_filas`: no se entrega un archivo recortado."""
    validar_filtros(coop, filtros, usuario)
    filas, total = repo.buscar_eventos(conn, filtros, alcance(usuario), 1, max_filas)
    if total > max_filas:
        raise problema(
            422,
            "EXPORTACION_MUY_GRANDE",
            f"El resultado supera {max_filas} filas; acote los filtros.",
        )
    return [_item(f) for f in filas]


def detalle(conn: Connection, id_auditoria: int, usuario: Usuario) -> EventoDetalle:
    fila = repo.obtener_evento(conn, id_auditoria)
    agencias = alcance(usuario)
    if fila is None or (agencias is not None and fila["IdAgencia"] not in agencias):
        raise problema(404, "EVENTO_NO_ENCONTRADO", "El evento no existe.")
    cambios = json.loads(fila["Cambios"]) if fila["Cambios"] else None
    if str(fila["TipoObjetivo"] or "").startswith("Clientes."):
        cambios = enmascarar_cambios(cambios)
    solicitud = repo.obtener_aprobacion(conn, id_auditoria)
    relacionados = (
        repo.obtener_relacionados(conn, fila["IdCorrelacion"], id_auditoria, agencias)
        if fila["IdCorrelacion"]
        else []
    )
    return EventoDetalle(
        **_item(fila).model_dump(),
        cambios=cambios,
        aprobacion=Aprobacion(
            id_solicitud=solicitud["IdSolicitud"],
            operacion=solicitud["CodigoTransaccion"],
            estado=solicitud["Estado"],
            solicitante=Persona(
                nombre=solicitud["NombreSolicitante"],
                id_interno=solicitud["IdInternoSolicitante"],
            ),
            fecha_solicitud=solicitud["FechaSolicitud"],
            aprobador=Persona(
                nombre=solicitud["NombreResolutor"],
                id_interno=solicitud["IdInternoResolutor"],
            )
            if solicitud["NombreResolutor"] or solicitud["IdInternoResolutor"]
            else None,
            fecha_resolucion=solicitud["FechaResolucion"],
        )
        if solicitud
        else None,
        relacionados=[_item(r) for r in relacionados],
    )


def tipos_evento(conn: Connection) -> list[TipoEvento]:
    return [
        TipoEvento(
            codigo=f["CodigoEvento"], modulo=f["Modulo"], severidad=f["Severidad"]
        )
        for f in repo.listar_tipos_evento(conn)
    ]


def eventos_objetivo(
    conn: Connection,
    tipo: str,
    id_objetivo: str,
    usuario: Usuario,
    page: int,
    page_size: int,
) -> PageEventos:
    filas, total = repo.eventos_objetivo(
        conn, tipo, id_objetivo, alcance(usuario), page, page_size
    )
    return PageEventos(
        items=[_item(f) for f in filas], total=total, page=page, page_size=page_size
    )
