"""Contenido canonico y huella estable; nunca convierte una solicitud en ejecutada."""

import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException

from app.core.api.errors import problema

_MAX_BYTES = 65536
_CLAVES_SECRETAS = frozenset(
    {
        "password",
        "contrasena",
        "contraseña",
        "pin",
        "pan",
        "token",
        "accesstoken",
        "refreshtoken",
        "authorization",
        "cookie",
        "secret",
        "secreto",
        "numerotarjeta",
    }
)


def _validar_nodos(valor: Any, profundidad: int = 0) -> None:
    if profundidad > 20:
        raise ValueError("Contenido demasiado profundo")
    if isinstance(valor, dict):
        for clave, elemento in valor.items():
            if not isinstance(clave, str) or not clave or len(clave) > 100:
                raise ValueError("Clave no valida")
            normalizada = clave.casefold().replace("_", "").replace("-", "")
            if normalizada in _CLAVES_SECRETAS:
                raise ValueError("Campo secreto no admitido")
            _validar_nodos(elemento, profundidad + 1)
    elif isinstance(valor, list):
        for elemento in valor:
            _validar_nodos(elemento, profundidad + 1)
    elif valor is not None and not isinstance(valor, (str, int, float, bool)):
        raise ValueError("Solo JSON tipado por el manejador")


@dataclass(frozen=True)
class ContenidoCongelado:
    texto: str
    huella: bytes


def congelar(contenido: dict[str, Any]) -> ContenidoCongelado:
    try:
        if not isinstance(contenido, dict):
            raise TypeError("Se requiere un objeto JSON")
        _validar_nodos(contenido)
        texto = json.dumps(
            contenido,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        codificado = texto.encode("utf-8")
        if len(codificado) > _MAX_BYTES:
            raise ValueError("Contenido demasiado grande")
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise problema(
            422, "CONTENIDO_INVALIDO", "El contenido de la solicitud no es valido."
        ) from None
    return ContenidoCongelado(texto, hashlib.sha256(codificado).digest())


def verificar(texto: str, huella: bytes) -> dict[str, Any]:
    try:
        if len(texto.encode("utf-8")) > _MAX_BYTES or len(huella) != 32:
            raise ValueError
        if not hmac.compare_digest(
            hashlib.sha256(texto.encode("utf-8")).digest(), huella
        ):
            raise ValueError
        contenido = json.loads(texto)
        if not isinstance(contenido, dict):
            raise TypeError
        # Canonico exacto: ni NaN, ni claves duplicadas ni representaciones ambiguas.
        if congelar(contenido).texto != texto:
            raise ValueError
    except (ValueError, TypeError, UnicodeError, HTTPException):
        raise problema(
            409, "CONTENIDO_ALTERADO", "La integridad de la solicitud no es valida."
        ) from None
    return contenido
