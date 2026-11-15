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
from app.modules.productos import service, vinculos
from app.modules.productos.schemas import (
    CupoCanalVista,
    CuposSubProducto,
    Producto,
    ProductoCreate,
    ProductoUpdate,
    RestriccionesSubProducto,
    RestriccionesVista,
    SubProducto,
    SubProductoCreate,
    SubProductoUpdate,
    VinculosEntrada,
    VinculosVista,
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
@router.get(
    "/subproductos/{id_sub_producto}/vinculos",
    operation_id="PRDSubVinculos",
    response_model=VinculosVista,
    openapi_extra={"x-roles": _LECTURA},
)
def obtener_vinculos_subproducto(
    id_sub_producto: IdPath, _: Lector, conn: Db
) -> VinculosVista:
    """Tasas, comisiones, seguros y amortización del subproducto, y los del producto."""
    return vinculos.obtener(conn, "subproducto", id_sub_producto)


@router.put(
    "/subproductos/{id_sub_producto}/vinculos",
    operation_id="PRDSubVinculosGuardar",
    response_model=VinculosVista,
    openapi_extra={"x-roles": _ESCRITURA},
)
def guardar_vinculos_subproducto(
    id_sub_producto: IdPath,
    payload: VinculosEntrada,
    request: Request,
    usuario: Administrador,
    conn: Db,
) -> VinculosVista:
    return vinculos.guardar(
        conn,
        "subproducto",
        id_sub_producto,
        payload,
        usuario,
        ip_cliente(request.scope),
    )


@router.get(
    "/subproductos/{id_sub_producto}/cupos",
    operation_id="PRDSubCupos",
    response_model=list[CupoCanalVista],
    openapi_extra={"x-roles": _LECTURA},
)
def listar_cupos(id_sub_producto: IdPath, _: Lector, conn: Db) -> list[CupoCanalVista]:
    """Cuentas y tarjetas: máximos por canal (diario, mensual, por transacción, número)."""
    return service.listar_cupos(conn, id_sub_producto)


@router.put(
    "/subproductos/{id_sub_producto}/cupos",
    operation_id="PRDSubCuposGuardar",
    response_model=list[CupoCanalVista],
    openapi_extra={"x-roles": _ESCRITURA},
)
def guardar_cupos(
    id_sub_producto: IdPath,
    payload: CuposSubProducto,
    request: Request,
    usuario: Administrador,
    conn: Db,
) -> list[CupoCanalVista]:
    """Reemplaza los canales habilitados y sus máximos."""
    return service.guardar_cupos(
        conn, id_sub_producto, payload, usuario, ip_cliente(request.scope)
    )


@router.get(
    "/subproductos/{id_sub_producto}/restricciones",
    operation_id="PRDSubRestricciones",
    response_model=RestriccionesVista,
    openapi_extra={"x-roles": _LECTURA},
)
def obtener_restricciones(
    id_sub_producto: IdPath, _: Lector, conn: Db
) -> RestriccionesVista:
    """Cuentas: días sin retiros desde la apertura y saldo mínimo."""
    return service.obtener_restricciones(conn, id_sub_producto)


@router.put(
    "/subproductos/{id_sub_producto}/restricciones",
    operation_id="PRDSubRestriccionesGuardar",
    response_model=RestriccionesVista,
    openapi_extra={"x-roles": _ESCRITURA},
)
def guardar_restricciones(
    id_sub_producto: IdPath,
    payload: RestriccionesSubProducto,
    request: Request,
    usuario: Administrador,
    conn: Db,
) -> RestriccionesVista:
    return service.guardar_restricciones(
        conn, id_sub_producto, payload, usuario, ip_cliente(request.scope)
    )


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


@router.get(
    "/{id_producto}/vinculos",
    operation_id="PRDVinculos",
    response_model=VinculosVista,
    openapi_extra={"x-roles": _LECTURA},
)
def obtener_vinculos_producto(
    id_producto: IdPath, _: Lector, conn: Db
) -> VinculosVista:
    """Lo vinculado al producto aplica a todos sus subproductos."""
    return vinculos.obtener(conn, "producto", id_producto)


@router.put(
    "/{id_producto}/vinculos",
    operation_id="PRDVinculosGuardar",
    response_model=VinculosVista,
    openapi_extra={"x-roles": _ESCRITURA},
)
def guardar_vinculos_producto(
    id_producto: IdPath,
    payload: VinculosEntrada,
    request: Request,
    usuario: Administrador,
    conn: Db,
) -> VinculosVista:
    return vinculos.guardar(
        conn, "producto", id_producto, payload, usuario, ip_cliente(request.scope)
    )
