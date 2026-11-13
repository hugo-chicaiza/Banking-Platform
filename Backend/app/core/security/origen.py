"""Origen del FE en cada petición: FRONTEND_URL o, solo en backend-dev, el de una
preview de PR de Cloudflare.

Sin FRONTEND_ORIGIN_REGEX (producción) el origen es siempre FRONTEND_URL. Con ella, el
Worker de Cloudflare manda en X-Forwarded-Host el host de la preview (sobrescribe el
que envíe el cliente). Si ese host es válido y cumple la regex, es el origen del login,
del callback, del logout y del control CSRF; si no, se usa FRONTEND_URL.

Quien llame a backend-dev directamente con su propio X-Forwarded-Host solo puede elegir
entre hosts que acepta la regex (los de la cuenta), y las cookies `__Host-` pertenecen
al host de la preview, así que nunca recibe la sesión de otro.
"""

import logging
import re

from fastapi import Request

from app.core.config.settings import get_settings
from app.integrations.workos_client import get_frontend_url

logger = logging.getLogger(__name__)

# Lista blanca (ya en minúsculas): sin puerto, coma, espacios, saltos de línea, "/" ni
# "@", y a lo sumo 253 caracteres (máximo de un nombre DNS)
_HOST_VALIDO = re.compile(r"[a-z0-9.-]{1,253}")


def resolver_origen_front(request: Request) -> str:
    """esquema://host del FE que hizo la petición; FRONTEND_URL ante cualquier duda.

    Los logs de depuración (LOG_LEVEL=DEBUG) dicen por qué se descartó la cabecera,
    sin volcar valores que no pasaron la validación.
    """
    frontal = get_frontend_url()
    regex = get_settings().frontend_origin_regex
    if not regex:
        return frontal

    hosts = request.headers.getlist("x-forwarded-host")
    if len(hosts) != 1:
        logger.debug(
            "origen: %d cabeceras X-Forwarded-Host, se usa FRONTEND_URL", len(hosts)
        )
        return frontal
    host = hosts[0].lower()
    if "," in host:
        logger.debug(
            "origen: X-Forwarded-Host con %d valores separados por coma, se usa "
            "FRONTEND_URL",
            host.count(",") + 1,
        )
        return frontal
    # fullmatch y no match: "^...$" con match deja pasar un salto de línea final
    if not _HOST_VALIDO.fullmatch(host):
        logger.debug(
            "origen: X-Forwarded-Host inválido longitud=%d, se usa FRONTEND_URL",
            len(host),
        )
        return frontal

    candidato = f"https://{host}"
    if not re.fullmatch(regex, candidato):
        # host ya validado: solo [a-z0-9.-], seguro para el log
        logger.debug("origen: host fuera de FRONTEND_ORIGIN_REGEX host=%s", host)
        return frontal
    if candidato != frontal:
        logger.debug("origen: preview origen=%s", candidato)
    return candidato
