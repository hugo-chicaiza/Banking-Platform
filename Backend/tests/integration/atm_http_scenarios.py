"""Escenarios compartidos de autenticacion ATM; solo datos sinteticos de fixtures."""

from datetime import UTC, datetime

import jwt

from app.modules.atm import session


def preparar_fallo_autenticacion(cliente, caso):
    headers = dict(cliente.headers)
    if caso in {"ausente", "credencial"}:
        headers.pop("Authorization" if caso == "ausente" else "X-ATM-Credential")
    elif caso == "invalido":
        headers["Authorization"] = "Bearer falso"
    elif caso == "expirado":
        claims = jwt.decode(cliente.token, options={"verify_signature": False})
        claims.update(iat=int(datetime.now(UTC).timestamp()) - 600)
        claims["exp"] = claims["iat"] + 300
        firmado = jwt.encode(
            claims, session.preparar_emisor_atm().clave, algorithm="RS256"
        )
        headers["Authorization"] = "Bearer " + firmado
    elif caso == "revocado":
        cliente.revocada = True
    else:
        cambios = {
            "version": {"fecha_asignacion": datetime(2026, 11, 2)},
            "restringido": {"requiere_cambio": True},
            "bloqueado": {"estado_pin": "Bloqueado"},
            "coordinacion": {"coordinacion_pendiente": True},
        }
        if caso not in cambios:
            raise ValueError("Escenario de prueba desconocido")
        cliente.pin.update(cambios[caso])
    return headers
