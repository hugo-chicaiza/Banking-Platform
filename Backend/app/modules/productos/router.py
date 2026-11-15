"""Productos y subproductos (plan E3-02): ADMIN crea y edita; ADMIN y ASESOR consultan.

Mientras no existan los permisos en tablas (E0-04), el acceso es por rol, como el resto
de los módulos. Sin DELETE: la baja es lógica por Estado.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request
from sqlalchemy import Connection

from app.core.api.errors import RESPUESTAS_ERROR, ProblemDetailsRoute, solo_parametros
from app.core.api.middleware import ip_cliente
from app.core.database.db import cooperativa
from app.core.security.auth import Usuario, require_auth, require_roles
from app.modules.productos import service
from app.modules.productos.schemas import (
    Producto,
    ProductoCreate,
    ProductoUpdate,
    SubProducto,
    SubProductoCreate,
    SubProductoUpdate,
)

_LECTURA = ["ADMIN", "ASESOR"]
_ESCRITURA = ["ADMIN"]

router = APIRouter(
    prefix="/productos",
    tags=["productos"],
    route_class=ProblemDetailsRoute,
    responses=RESPUESTAS_ERROR,
    dependencies=[Depends(require_auth), Depends(solo_parametros())],
)
Db = Annotated[Connection, Depends(cooperativa)]
IdPath = Annotated[int, Path(ge=1, le=2_147_483_647)]
Lector = Annotated[Usuario, Depends(require_roles(*_LECTURA))]
Administrador = Annotated[Usuario, Depends(require_roles(*_ESCRITURA))]


@router.get(
    "",
    operation_id="PRDListar",
    response_model=list[Producto],
    openapi_extra={"x-roles": _LECTURA},
)
def listar_productos(_: Lector, conn: Db) -> list[Producto]:
    """Todos los productos (activos e inactivos) con todos sus subproductos."""
    return service.listar_productos(conn)


@router.get(
    "/{id_producto}",
    operation_id="PRDObtener",
    response_model=Producto,
    openapi_extra={"x-roles": _LECTURA},
)
def obtener_producto(id_producto: IdPath, _: Lector, conn: Db) -> Producto:
    return service.obtener_producto(conn, id_producto)


@router.post(
    "",
    operation_id="PRDCrear",
    response_model=Producto,
    status_code=201,
    openapi_extra={"x-roles": _ESCRITURA},
)
def crear_producto(
    payload: ProductoCreate, request: Request, usuario: Administrador, conn: Db
) -> Producto:
    """Crea el producto Inactivo; se activa cuando tiene al menos un subproducto."""
    return service.crear_producto(conn, payload, usuario, ip_cliente(request.scope))


# Antes de /{id_producto}: si no, «subproductos» se tomaría como id de producto
@router.patch(
    "/subproductos/{id_sub_producto}",
    operation_id="PRDSubEditar",
    response_model=SubProducto,
    openapi_extra={"x-roles": _ESCRITURA},
)
def actualizar_subproducto(
    id_sub_producto: IdPath,
    payload: SubProductoUpdate,
    request: Request,
    usuario: Administrador,
    conn: Db,
) -> SubProducto:
    return service.actualizar_subproducto(
        conn, id_sub_producto, payload, usuario, ip_cliente(request.scope)
    )


@router.patch(
    "/{id_producto}",
    operation_id="PRDEditar",
    response_model=Producto,
    openapi_extra={"x-roles": _ESCRITURA},
)
def actualizar_producto(
    id_producto: IdPath,
    payload: ProductoUpdate,
    request: Request,
    usuario: Administrador,
    conn: Db,
) -> Producto:
    return service.actualizar_producto(
        conn, id_producto, payload, usuario, ip_cliente(request.scope)
    )


@router.post(
    "/{id_producto}/subproductos",
    operation_id="PRDSubCrear",
    response_model=SubProducto,
    status_code=201,
    openapi_extra={"x-roles": _ESCRITURA},
)
def crear_subproducto(
    id_producto: IdPath,
    payload: SubProductoCreate,
    request: Request,
    usuario: Administrador,
    conn: Db,
) -> SubProducto:
    return service.crear_subproducto(
        conn, id_producto, payload, usuario, ip_cliente(request.scope)
    )
