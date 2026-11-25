"""Lo que cada usuario ve del cliente; ninguna respuesta lleva datos sensibles completos.

E5-05 (ASVS 8.2.3, 14.2.6, 15.3.1): documento, correo y teléfonos salen enmascarados del
servidor para todos; el valor completo solo se entrega por la revelación auditada con
MFA (revelacion.py). El cajero ve una ficha reducida, sin direcciones.
"""

from app.core.csv import enmascarar_documento
from app.core.security.auth import Usuario
from app.modules.clientes.schemas import Cliente, ClientePerfil, PageCliente
from app.modules.seguridad import funciones

ROLES_FICHA_COMPLETA = frozenset({"ASESOR", "SUPERVISOR", "ADMIN"})


def puede_ver_direcciones(usuario: Usuario) -> bool:
    if not ficha_completa(usuario):
        return False
    # Con el editor apagado se conserva el contrato de permisos anterior.
    if not funciones.activa():
        return True
    return "clientes.direcciones.consultar" in funciones.efectivos(usuario).funciones


def ficha_completa(usuario: Usuario) -> bool:
    return bool(ROLES_FICHA_COMPLETA & set(usuario.roles))


def enmascarar_email(valor: str | None) -> str | None:
    if not valor:
        return valor
    local, arroba, dominio = valor.partition("@")
    if not arroba:
        return enmascarar_documento(valor)
    return (local[:1] if len(local) > 1 else "") + "***@" + dominio


def enmascarar_telefono(valor: str | None) -> str | None:
    return valor if not valor else enmascarar_documento(valor)


def enmascarar(cliente: Cliente, *, con_direcciones: bool) -> Cliente:
    return cliente.model_copy(
        update={
            "identificacion": enmascarar_documento(cliente.identificacion),
            "email": enmascarar_email(cliente.email),
            "telefono_celular": enmascarar_telefono(cliente.telefono_celular),
            "telefono_convencional": enmascarar_telefono(cliente.telefono_convencional),
            "direcciones": cliente.direcciones if con_direcciones else [],
        }
    )


def aplicar_visibilidad[T: Cliente | ClientePerfil | PageCliente](
    datos: T, usuario: Usuario, *, permitido: bool | None = None
) -> T:
    if permitido is None:
        permitido = puede_ver_direcciones(usuario)
    if isinstance(datos, PageCliente):
        return datos.model_copy(
            update={
                "items": [enmascarar(c, con_direcciones=permitido) for c in datos.items]
            }
        )
    if isinstance(datos, ClientePerfil):
        return datos.model_copy(
            update={"cliente": enmascarar(datos.cliente, con_direcciones=permitido)}
        )
    return enmascarar(datos, con_direcciones=permitido)
