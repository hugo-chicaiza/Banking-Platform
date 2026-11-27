"""E8-01 · Consultar la bitácora de auditoría (#412).

Lectura: ADMIN, SUPERVISOR y AUDITOR; exportación: ADMIN y AUDITOR con el permiso de
exportar. El 403 queda registrado por AccesoDenegadoMiddleware (ASVS 16.3.2) y cada
lectura exitosa como AUD_LECTURA. Los filtros van en el cuerpo, nunca en la URL.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query, Request, Response
from sqlalchemy import Connection

from app.core import csv as csv_tool
from app.core import pdf as pdf_tool
from app.core.api.errors import RESPUESTAS_ERROR, ProblemDetailsRoute
from app.core.api.middleware import ip_cliente
from app.core.database.db import cooperativa, get_engine, seguridad
from app.core.security import audit
from app.core.security.auth import Usuario, require_auth, require_roles
from app.modules.auditoria import service
from app.modules.auditoria.schemas import (
    EventoDetalle,
    FiltrosBusqueda,
    FiltrosExportacion,
    PageEventos,
    TipoEvento,
)

_LECTURA = ("ADMIN", "SUPERVISOR", "AUDITOR")
_EXPORTACION = ("ADMIN", "AUDITOR")
MAX_FILAS_EXPORTACION = 1000


def _sin_cache(response: Response) -> None:
    """ASVS 14.3.2: la bitácora no queda en cachés del navegador ni intermedias."""
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(
    prefix="/auditoria",
    tags=["auditoria"],
    route_class=ProblemDetailsRoute,
    responses=RESPUESTAS_ERROR,
    dependencies=[Depends(require_auth), Depends(_sin_cache)],
)
Seg = Annotated[Connection, Depends(seguridad)]
Coop = Annotated[Connection, Depends(cooperativa)]
# El rol se comprueba en `dependencies`, antes de abrir conexiones (403, no 500)
Lector = Annotated[Usuario, Depends(require_auth)]
Exportador = Lector
_ROL_LECTURA = [Depends(require_roles(*_LECTURA))]
_X_LECTURA = {"x-roles": list(_LECTURA)}


def _evento(
    usuario: Usuario,
    request: Request,
    accion: str,
    descripcion: str,
    filtros: dict[str, Any],
    id_registro: str | None = None,
) -> audit.EventoAuditoria:
    return audit.EventoAuditoria(
        accion=accion,
        tabla="Auditoria.Auditoria",
        id_registro=id_registro,
        resultado="Exitoso",
        usuario=usuario.interno(),
        ip=ip_cliente(request.scope),
        descripcion=descripcion,
        roles=usuario.roles_texto(),
        agencia=usuario.agencia(),
        sesion=usuario.id_sesion,
        cambios={"filtros": {k: v for k, v in filtros.items() if v is not None}},
    )


@router.post(
    "/eventos/busqueda",
    operation_id="AUDBuscarEventos",
    response_model=PageEventos,
    dependencies=_ROL_LECTURA,
    openapi_extra=_X_LECTURA,
)
def buscar_eventos(
    filtros: FiltrosBusqueda,
    request: Request,
    conn: Seg,
    coop: Coop,
    usuario: Lector,
) -> PageEventos:
    """Eventos por rango de fechas (obligatorio) y filtros, del más reciente al más antiguo."""
    datos = filtros.model_dump()
    pagina = service.buscar(conn, coop, datos, usuario)
    audit.registrar(
        _evento(
            usuario, request, "AUD_LECTURA", f"busqueda filas={pagina.total}", datos
        )
    )
    return pagina


@router.get(
    "/eventos/{idEvento}",
    operation_id="AUDDetalleEvento",
    response_model=EventoDetalle,
    dependencies=_ROL_LECTURA,
    openapi_extra=_X_LECTURA,
)
def detalle_evento(
    id_evento: Annotated[int, Path(alias="idEvento", ge=1, le=2147483647)],
    request: Request,
    conn: Seg,
    usuario: Lector,
) -> EventoDetalle:
    """Registro, antes y después, aprobación y los demás eventos de la misma petición."""
    evento = service.detalle(conn, id_evento, usuario)
    audit.registrar(
        _evento(
            usuario,
            request,
            "AUD_LECTURA",
            "detalle",
            {"idEvento": id_evento},
            str(id_evento),
        )
    )
    return evento


@router.get(
    "/tipos-evento",
    operation_id="AUDTiposEvento",
    response_model=list[TipoEvento],
    dependencies=_ROL_LECTURA,
    openapi_extra=_X_LECTURA,
)
def tipos_evento(conn: Seg, _usuario: Lector) -> list[TipoEvento]:
    return service.tipos_evento(conn)


@router.get(
    "/objetivos/{tipo}/{id}/eventos",
    operation_id="AUDEventosObjetivo",
    response_model=PageEventos,
    dependencies=_ROL_LECTURA,
    openapi_extra=_X_LECTURA,
)
def eventos_objetivo(
    tipo: Annotated[str, Path(pattern=r"^[A-Za-z0-9_.]{1,100}$")],
    id_objetivo: Annotated[str, Path(alias="id", pattern=r"^[A-Za-z0-9_.:-]{1,100}$")],
    request: Request,
    conn: Seg,
    usuario: Lector,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=100)] = 25,
) -> PageEventos:
    """Pestaña Historial: los eventos de un cliente, cuenta, transacción, usuario, etc."""
    pagina = service.eventos_objetivo(conn, tipo, id_objetivo, usuario, page, page_size)
    audit.registrar(
        _evento(
            usuario,
            request,
            "AUD_LECTURA",
            f"objetivo {tipo}",
            {"tipo": tipo, "id": id_objetivo},
            id_objetivo,
        )
    )
    return pagina


_COLUMNAS = (
    "id",
    "fechaHoraLocal",
    "codigoEvento",
    "modulo",
    "severidad",
    "usuario",
    "nombreUsuario",
    "agencia",
    "canal",
    "origen",
    "resultado",
    "tipoObjetivo",
    "idObjetivo",
    "correlacion",
    "descripcion",
    "formatoAnterior",
)


@router.post(
    "/eventos/exportacion",
    operation_id="AUDExportarEventos",
    response_class=Response,
    dependencies=[Depends(require_roles(*_EXPORTACION))],
    responses={
        **RESPUESTAS_ERROR,
        **csv_tool.RESPUESTA_CSV,
        **pdf_tool.respuestas_pdf("Bitácora de auditoría en PDF"),
    },
    openapi_extra={
        "x-roles": list(_EXPORTACION),
        "x-permissions": [csv_tool.PERMISO_EXPORTAR],
    },
)
def exportar_eventos(
    filtros: FiltrosExportacion,
    request: Request,
    conn: Seg,
    coop: Coop,
    usuario: Exportador,
) -> Response:
    """CSV o PDF de la búsqueda, hasta 1000 filas; se registra antes de entregar."""
    csv_tool.autorizar(usuario)
    datos = filtros.model_dump()
    eventos = service.para_exportar(conn, coop, datos, usuario, MAX_FILAS_EXPORTACION)
    filas = [
        (
            e.id,
            e.fecha_hora_local.isoformat() if e.fecha_hora_local else "",
            e.codigo_evento,
            e.modulo,
            e.severidad,
            e.usuario,
            e.nombre_usuario,
            e.agencia,
            e.canal,
            e.origen,
            e.resultado,
            e.tipo_objetivo,
            e.id_objetivo,
            e.correlacion,
            e.descripcion,
            "Sí" if e.formato_anterior else "No",
        )
        for e in eventos
    ]
    if filtros.formato == "csv":
        return csv_tool.responder_csv(
            usuario,
            ip_cliente(request.scope),
            "bitacora-auditoria",
            "Auditoria.Auditoria",
            _COLUMNAS,
            filas,
            evento="AUD_EXPORTACION",
            max_filas=MAX_FILAS_EXPORTACION,
        )
    doc = pdf_tool.DocumentoPdf(
        "Bitácora de auditoría",
        institucion=pdf_tool.institucion_actual(coop),
        generado_por=usuario.nombre,
    )
    doc.campos(
        [
            (clave, str(valor))
            for clave, valor in filtros.model_dump(by_alias=True).items()
            if valor is not None and clave not in ("page", "pageSize")
        ]
    )
    doc.tabla(
        ["Fecha", "Evento", "Usuario", "Agencia", "Resultado", "Objetivo"],
        [
            [
                str(f[1])[:19],
                str(f[2] or ""),
                str(f[6] or f[5] or ""),
                str(f[7] or ""),
                str(f[10] or ""),
                f"{f[11] or ''} {f[12] or ''}".strip(),
            ]
            for f in filas
        ],
    )
    contenido = doc.contenido()
    # ASVS 16.2.5: sin registro no se entrega el archivo
    with get_engine("seguridad").begin() as registro:
        audit.registrar_en_transaccion(
            registro,
            _evento(
                usuario,
                request,
                "AUD_EXPORTACION",
                f"formato=pdf filas={len(filas)}",
                datos,
            ),
        )
    return pdf_tool.respuesta_pdf(contenido, "bitacora-auditoria")
