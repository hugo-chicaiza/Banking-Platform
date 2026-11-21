"""Generación de PDF común a todos los módulos (ver documento.py)."""

from app.core.pdf.documento import DocumentoPdf, texto_pdf
from app.core.pdf.institucion import (
    Institucion,
    institucion_actual,
    institucion_por_defecto,
)
from app.core.pdf.respuesta import nombre_archivo, respuesta_pdf, respuestas_pdf

__all__ = [
    "DocumentoPdf",
    "Institucion",
    "institucion_actual",
    "institucion_por_defecto",
    "nombre_archivo",
    "respuesta_pdf",
    "respuestas_pdf",
    "texto_pdf",
]
