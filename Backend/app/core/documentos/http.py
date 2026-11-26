"""El «enlace» de un documento: la ruta de cada módulo que lo entrega.

MongoDB no sirve archivos por HTTP y su URI nunca sale del backend. El enlace es una
ruta del módulo dueño del documento, p. ej. `GET /api/v1/clientes/{id}/archivos/
{idArchivo}/contenido`: comprueba el permiso, audita, lee la `clave` de su tabla y
responde con `respuesta_documento`. Las respuestas del módulo incluyen esa ruta como
`urlContenido`; el navegador la abre con la sesión del usuario (cookie por el Worker).
"""

from typing import Any

from fastapi import HTTPException, Response

from app.core.api.errors import problema
from app.core.documentos.servicio import (
    EXTENSION,
    AlmacenamientoNoDisponible,
    ArchivoMuyGrande,
    ArchivoRechazado,
    Documento,
    DocumentoNoDisponible,
    DocumentoNoEncontrado,
    ErrorDocumento,
    TipoNoPermitido,
)
from app.core.pdf import nombre_archivo


def problema_documento(exc: ErrorDocumento) -> HTTPException:
    """Error del almacenamiento → respuesta HTTP (E5-08: 413, 415, 422, 503)."""
    if isinstance(exc, ArchivoMuyGrande):
        return problema(
            413, "ARCHIVO_MUY_GRANDE", "El archivo supera el tamaño máximo (5 MB)."
        )
    if isinstance(exc, TipoNoPermitido):
        return problema(
            415, "TIPO_NO_PERMITIDO", "Solo se aceptan archivos PDF, JPG o PNG."
        )
    if isinstance(exc, ArchivoRechazado):
        # Mensaje genérico: el motivo queda en el log, no orienta a quien prueba evadirlo
        return problema(
            422,
            "ARCHIVO_RECHAZADO",
            "El archivo no superó la revisión de seguridad y no se guardó.",
        )
    if isinstance(exc, DocumentoNoEncontrado):
        return problema(404, "DOCUMENTO_NO_ENCONTRADO", "El documento no existe.")
    if isinstance(exc, DocumentoNoDisponible):
        return problema(
            409,
            "DOCUMENTO_NO_DISPONIBLE",
            "El documento está en revisión de seguridad o fue rechazado.",
        )
    if isinstance(exc, AlmacenamientoNoDisponible):
        return problema(
            503,
            "ALMACENAMIENTO_NO_DISPONIBLE",
            "El almacenamiento de documentos no está disponible. Inténtalo más tarde.",
        )
    return problema(500, "ERROR_INTERNO", "Error interno del servidor.")


def respuesta_documento(documento: Documento, nombre: str) -> Response:
    """Siempre como descarga, con el tipo detectado al guardar (no el que dijo el
    cliente) y un nombre saneado: el original nunca se usa como ruta. Sin caché."""
    base = nombre_archivo(nombre)[:-4]  # sin el .pdf que agrega nombre_archivo
    # La extensión la pone el tipo detectado; la que traía el nombre se descarta
    if "." in base and base.rsplit(".", 1)[1].lower() in {"pdf", "png", "jpg", "jpeg"}:
        base = base.rsplit(".", 1)[0]
    extension = EXTENSION.get(documento.tipo_contenido, "bin")
    return Response(
        content=documento.contenido,
        media_type=documento.tipo_contenido,
        headers={
            "Content-Disposition": f'attachment; filename="{base}.{extension}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


def respuestas_documento(descripcion: str) -> dict[int | str, dict[str, Any]]:
    """`responses=` de la ruta de contenido para OpenAPI."""
    return {
        200: {
            "content": {t: {} for t in EXTENSION},
            "description": descripcion,
        }
    }
