"""Respuesta HTTP de un PDF, igual para todos los módulos."""

import re
from typing import Any

from fastapi import Response

_NOMBRE_SEGURO = re.compile(r"[^A-Za-z0-9._-]+")


def nombre_archivo(nombre: str) -> str:
    """Nombre para Content-Disposition: solo letras, números, punto, guion y guion
    bajo (sin rutas ni comillas), siempre terminado en .pdf."""
    base = _NOMBRE_SEGURO.sub("-", nombre.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]).strip(
        ".-"
    )
    base = (base[:-4] if base.lower().endswith(".pdf") else base).strip(".-")
    return f"{base[:100] or 'documento'}.pdf"


def respuesta_pdf(contenido: bytes, nombre: str, *, adjunto: bool = True) -> Response:
    """`adjunto=True` descarga el archivo; False lo abre en el navegador. Sin caché:
    los PDF suelen llevar datos del cliente o de la operación."""
    modo = "attachment" if adjunto else "inline"
    return Response(
        content=contenido,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'{modo}; filename="{nombre_archivo(nombre)}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


def respuestas_pdf(descripcion: str) -> dict[int | str, dict[str, Any]]:
    """`responses=` de la ruta para que OpenAPI documente el PDF."""
    return {200: {"content": {"application/pdf": {}}, "description": descripcion}}
