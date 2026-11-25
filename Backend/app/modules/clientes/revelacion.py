"""E5-05 · "Mostrar valor completo" con segundo factor (MFA de WorkOS) y auditoría.

Flujo: el usuario pide un desafío para su propio factor TOTP de AuthKit, escribe el
código de su app y la revelación devuelve solo los campos pedidos. No se guarda estado:
la verificación comprueba que el desafío pertenece a un factor del usuario de la sesión.
Cada intento, exitoso o fallido, se audita con quién, qué cliente y qué campos, nunca
con los valores (ASVS 6.3.3, 8.2.3, 16.2.1, 16.2.5, 16.3.1).
"""

import logging
from collections.abc import Iterable

import httpx
from sqlalchemy import Connection
from workos.exceptions import (
    BadRequestException,
    BaseRequestException,
    NotFoundException,
)

from app.core.api.errors import problema
from app.core.security import audit
from app.core.security.auth import Usuario, get_workos
from app.modules.clientes import correos, service
from app.modules.clientes.schemas import (
    DesafioRevelacion,
    Revelacion,
    SolicitudRevelacion,
)

logger = logging.getLogger(__name__)
EVENTO = "CLI_DATO_REVELADO"


def _no_disponible() -> Exception:
    return problema(
        503,
        "MFA_NO_DISPONIBLE",
        "No pudimos comprobar el segundo factor; intenta otra vez.",
    )


def _factores(usuario: Usuario) -> list[str]:
    try:
        factores = get_workos().user_management.list_auth_factors(
            user_id=usuario.id_usuario
        )
        return [f.id for f in factores if getattr(f, "type", None) == "totp"]
    except (BaseRequestException, httpx.HTTPError) as error:
        logger.warning(
            "revelacion: factores no disponibles tipo=%s", type(error).__name__
        )
        raise _no_disponible() from None


def desafiar(conn: Connection, id_cliente: int, usuario: Usuario) -> DesafioRevelacion:
    service.obtener_cliente(conn, id_cliente)  # 404 antes de molestar al usuario
    factores = _factores(usuario)
    if not factores:
        raise problema(
            409,
            "MFA_NO_CONFIGURADO",
            "Configura la verificación en dos pasos de tu cuenta para ver datos completos.",
        )
    try:
        reto = get_workos().mfa.challenge_factor(authentication_factor_id=factores[0])
    except (BaseRequestException, httpx.HTTPError) as error:
        logger.warning("revelacion: desafío no creado tipo=%s", type(error).__name__)
        raise _no_disponible() from None
    # Nunca se devuelve reto.code: solo el id para verificar.
    return DesafioRevelacion(id_desafio=reto.id, expira_en=reto.expires_at)


def _verificar(usuario: Usuario, solicitud: SolicitudRevelacion) -> bool:
    factores = set(_factores(usuario))
    try:
        respuesta = get_workos().mfa.verify_challenge(
            authentication_challenge_id=solicitud.id_desafio, code=solicitud.codigo
        )
    except (BadRequestException, NotFoundException):
        return False  # código vencido, ya usado o desafío inexistente
    except (BaseRequestException, httpx.HTTPError) as error:
        logger.warning(
            "revelacion: verificación no disponible tipo=%s", type(error).__name__
        )
        raise _no_disponible() from None
    return bool(respuesta.valid) and (
        respuesta.challenge.authentication_factor_id in factores
    )


def _auditar(
    id_cliente: int,
    campos: Iterable[str],
    resultado: audit.Resultado,
    usuario: int,
    ip: str,
) -> None:
    audit.registrar(
        audit.EventoAuditoria(
            accion=EVENTO,
            tabla="Clientes.Cliente",
            id_registro=str(id_cliente),
            resultado=resultado,
            usuario=usuario,
            ip=ip,
            descripcion="Campos: " + ", ".join(campos),
        )
    )


def revelar(
    conn: Connection,
    id_cliente: int,
    solicitud: SolicitudRevelacion,
    usuario: Usuario,
    id_interno: int,
    ip: str,
) -> Revelacion:
    cliente = service.obtener_cliente(conn, id_cliente)
    if not _verificar(usuario, solicitud):
        _auditar(id_cliente, solicitud.campos, "Fallido", id_interno, ip)
        # 422 y no 403: es un dato mal escrito, no falta de permiso (el 403 lo audita
        # además el middleware de accesos denegados y quedaría dos veces).
        raise problema(
            422, "MFA_INVALIDO", "El código no es válido o venció; pide uno nuevo."
        )
    pedidos = set(solicitud.campos)
    revelado = Revelacion(
        identificacion=cliente.identificacion if "identificacion" in pedidos else None,
        email=cliente.email if "email" in pedidos else None,
        telefono_celular=cliente.telefono_celular
        if "telefonoCelular" in pedidos
        else None,
        telefono_convencional=cliente.telefono_convencional
        if "telefonoConvencional" in pedidos
        else None,
        correos_secundarios=[
            fila["email"] for fila in correos.listar_activos(conn, id_cliente)
        ]
        if "correosSecundarios" in pedidos
        else None,
    )
    _auditar(id_cliente, solicitud.campos, "Exitoso", id_interno, ip)
    return revelado
