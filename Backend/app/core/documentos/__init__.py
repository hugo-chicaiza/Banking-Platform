"""Almacenamiento de documentos en MongoDB, común a todos los módulos (servicio.py)."""

from app.core.documentos.http import (
    problema_documento,
    respuesta_documento,
    respuestas_documento,
)
from app.core.documentos.servicio import (
    AlmacenamientoNoDisponible,
    ArchivoMuyGrande,
    ArchivoRechazado,
    Documento,
    DocumentoNoDisponible,
    DocumentoNoEncontrado,
    ErrorDocumento,
    Referencia,
    ServicioDocumentos,
    TipoNoPermitido,
    obtener_servicio,
)

__all__ = [
    "AlmacenamientoNoDisponible",
    "ArchivoMuyGrande",
    "ArchivoRechazado",
    "Documento",
    "DocumentoNoDisponible",
    "DocumentoNoEncontrado",
    "ErrorDocumento",
    "Referencia",
    "ServicioDocumentos",
    "TipoNoPermitido",
    "obtener_servicio",
    "problema_documento",
    "respuesta_documento",
    "respuestas_documento",
]
