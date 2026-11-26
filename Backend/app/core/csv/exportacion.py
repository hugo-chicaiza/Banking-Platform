"""Exportación CSV común a todos los módulos (E1-14; antes en organizacion/).

Permiso explícito (`org-exportar`), neutralización de fórmulas (OWASP ASVS 5.0 1.2.10:
inyección CSV), registro de auditoría antes de entregar (ASVS 16.2.5) y respuesta sin
caché como descarga (ASVS 14.2.4: datos sensibles fuera de cachés). Uso:

    return responder_csv(usuario, ip, "agencias", "Organizacion.Agencia",
                         ("idAgencia", "codigo"), filas, evento="CLI_EXPORTACION")
"""

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
EVENTO_EXPORTACION = "ORG_EXPORTACION"
# Una hoja de cálculo interpreta como fórmula la celda que empieza así (ASVS 1.2.10)
_PREFIJOS_FORMULA = ("=", "+", "-", "@")
_CONTROLES_INICIALES = ("\t", "\r", "\n")


def autorizar(usuario: Usuario) -> None:
    """403 sin el permiso explícito, aun para ADMIN."""
    if PERMISO_EXPORTAR not in usuario.permisos:
        raise problema(403, "SIN_PERMISO", "No tiene permiso para exportar listados.")


def celda_csv(valor: Any) -> Any:
    """Antepone `'` al texto que una hoja de cálculo ejecutaría como fórmula (también
    tras espacios o BOM, o si empieza con tab/CR/LF). Lo que no es texto no cambia."""
    if not isinstance(valor, str):
        return valor
    relevante = valor.lstrip(" \t\r\n\v\f﻿")
    if valor.startswith(_CONTROLES_INICIALES) or relevante.startswith(
        _PREFIJOS_FORMULA
    ):
        return "'" + valor
    return valor


def enmascarar_documento(valor: str | None) -> str:
    """Solo los 4 últimos caracteres visibles (minimización de datos, LOPDP)."""
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
    *,
    evento: str = EVENTO_EXPORTACION,
    max_filas: int | None = None,
) -> Response:
    """CSV como descarga. `evento` es el código de auditoría (p. ej. clientes usa
    "CLI_EXPORTACION"); con `max_filas`, un listado más largo responde 422
    EXPORTACION_MUY_GRANDE sin auditar ni entregar nada."""
    autorizar(usuario)
    salida = StringIO(newline="")
    csv_writer = csv.writer(salida)
    csv_writer.writerow(columnas)
    cantidad = 0
    for fila in filas:
        if max_filas is not None and cantidad >= max_filas:
            raise problema(
                422,
                "EXPORTACION_MUY_GRANDE",
                f"El listado supera {max_filas} filas; use filtros para acotarlo.",
            )
        csv_writer.writerow(celda_csv(celda) for celda in fila)
        cantidad += 1
    registro = EventoAuditoria(
        accion=evento,
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
        registrar_en_transaccion(conn, registro)
    return Response(
        salida.getvalue(),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{listado}.csv"',
            "Cache-Control": "no-store",
        },
    )
