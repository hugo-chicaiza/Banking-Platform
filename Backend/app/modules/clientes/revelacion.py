"""E5-05 · "Mostrar valor completo" con segundo factor y auditoría.

El MFA es la pieza común `app.core.security.mfa`: el desafío queda ligado a la acción
`clientes.revelar`, al cliente y a los campos pedidos, así que un código obtenido para
otro cliente, otros campos u otra acción no sirve aquí. Con REVELACION_EXIGE_MFA
apagado se revela sin código (pendiente E5-05). Cada intento, exitoso o fallido, se
audita con quién, qué cliente y qué campos, nunca con los valores (ASVS 8.2.3, 16.2.1,
16.2.5, 16.3.1).
"""

from collections.abc import Iterable

from sqlalchemy import Connection

from app.core.api.errors import problema
from app.core.config.settings import get_settings
from app.core.security import audit, mfa
from app.core.security.auth import Usuario
from app.modules.clientes import correos, service
from app.modules.clientes.schemas import (
    CampoRevelable,
    DesafioRevelacion,
    Revelacion,
    SolicitudRevelacion,
)

EVENTO = "CLI_DATO_REVELADO"
ACCION = "clientes.revelar"


def recurso(id_cliente: int, campos: Iterable[CampoRevelable]) -> str:
    """Lo que autoriza el código: este cliente y exactamente estos campos."""
    return f"cliente:{id_cliente}|campos:{','.join(sorted(set(campos)))}"


def desafiar(
    conn: Connection,
    id_cliente: int,
    usuario: Usuario,
    campos: list[CampoRevelable],
) -> DesafioRevelacion:
    service.obtener_cliente(conn, id_cliente)  # 404 antes de molestar al usuario
    if not get_settings().revelacion_exige_mfa:
        return DesafioRevelacion(requiere_codigo=False)
    desafio = mfa.pedir_desafio(usuario, ACCION, recurso(id_cliente, campos))
    return DesafioRevelacion(
        id_desafio=desafio.id_desafio,
        comprobante=desafio.comprobante,
        expira_en=desafio.expira_en,
    )


def _verificar(
    usuario: Usuario, id_cliente: int, solicitud: SolicitudRevelacion
) -> bool:
    if not get_settings().revelacion_exige_mfa:
        return True  # Pendiente E5-05: MFA apagado; el permiso y la auditoría siguen.
    return mfa.verificar(
        usuario,
        ACCION,
        recurso(id_cliente, solicitud.campos),
        solicitud.id_desafio,
        solicitud.comprobante,
        solicitud.codigo,
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
    if not _verificar(usuario, id_cliente, solicitud):
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
