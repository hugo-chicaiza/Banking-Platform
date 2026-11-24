"""CSV institucional con permiso explícito y registro previo a la descarga."""

import csv
from collections.abc import Iterable, Sequence
from io import StringIO
from typing import Any

from fastapi import Response

from app.core.api.errors import problema
from app.core.database.db import get_engine
from app.core.security.audit import EventoAuditoria, registrar_en_transaccion
from app.core.security.auth import Usuario
from app.core.security.operador import exigir_id_interno

RESPUESTA_CSV: dict[int | str, dict[str, Any]] = {
    200: {"content": {"text/csv": {"schema": {"type": "string"}}}}
}
PERMISO_EXPORTAR = "org-exportar"


def autorizar(usuario: Usuario) -> None:
    if PERMISO_EXPORTAR not in usuario.permisos:
        raise problema(403, "SIN_PERMISO", "No tiene permiso para exportar listados.")


def celda_csv(valor: Any) -> Any:
    if not isinstance(valor, str):
        return valor
    relevante = valor.lstrip(" \t\r\n\v\f\ufeff")
    if valor.startswith(("\t", "\r", "\n")) or relevante.startswith(
        ("=", "+", "-", "@")
    ):
        return "'" + valor
    return valor


def enmascarar_documento(valor: str | None) -> str:
    documento = (valor or "").strip()
    if len(documento) <= 4:
        return "*" * len(documento)
    return "*" * (len(documento) - 4) + documento[-4:]


def responder_csv(
    usuario: Usuario,
    ip: str,
    listado: str,
    tabla: str,
    columnas: Sequence[str],
    filas: Iterable[Sequence[Any]],
) -> Response:
    autorizar(usuario)
    salida = StringIO(newline="")
    csv_writer = csv.writer(salida)
    csv_writer.writerow(columnas)
    cantidad = 0
    for fila in filas:
        csv_writer.writerow(celda_csv(celda) for celda in fila)
        cantidad += 1
    evento = EventoAuditoria(
        accion="ORG_EXPORTACION",
        tabla=tabla,
        id_registro=None,
        resultado="Exitoso",
        usuario=exigir_id_interno(usuario.interno()),
        ip=ip,
        descripcion=f"listado={listado} filas={cantidad}",
        roles=usuario.roles_texto(),
        sesion=usuario.id_sesion,
    )
    with get_engine("seguridad").begin() as conn:
        registrar_en_transaccion(conn, evento)
    return Response(
        salida.getvalue(),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{listado}.csv"',
            "Cache-Control": "no-store",
        },
    )
