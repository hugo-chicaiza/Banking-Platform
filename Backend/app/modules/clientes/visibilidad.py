"""Evita eludir el permiso de direcciones a través de respuestas compartidas."""

from app.core.security.auth import Usuario
from app.modules.clientes.schemas import Cliente, ClientePerfil, PageCliente
from app.modules.seguridad import funciones


def puede_ver_direcciones(usuario: Usuario) -> bool:
    # Con el editor apagado se conserva el contrato de permisos anterior.
    if not funciones.activa():
        return True
    return "clientes.direcciones.consultar" in funciones.efectivos(usuario).funciones


def aplicar_visibilidad[T: Cliente | ClientePerfil | PageCliente](
    datos: T, usuario: Usuario, *, permitido: bool | None = None
) -> T:
    if permitido is None:
        permitido = puede_ver_direcciones(usuario)
    if permitido:
        return datos
    if isinstance(datos, PageCliente):
        return datos.model_copy(
            update={
                "items": [c.model_copy(update={"direcciones": []}) for c in datos.items]
            }
        )
    if isinstance(datos, ClientePerfil):
        return datos.model_copy(
            update={"cliente": datos.cliente.model_copy(update={"direcciones": []})}
        )
    return datos.model_copy(update={"direcciones": []})
