"""Catalogo de productos con roles y permisos de la sesion WorkOS.

ADMIN escribe con PRD-EDITAR; ADMIN/ASESOR consultan con PRD-CONSULTAR.
La ficha imprimible exige ademas PRD-EXPORTAR. Solo se elimina un Borrador sin uso.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request, Response
from sqlalchemy import Connection

from app.core.api.errors import (
    RESPUESTAS_ERROR,
    ProblemDetailsRoute,
    problema,
    solo_parametros,
)
from app.core.api.middleware import ip_cliente
from app.core.database.db import cooperativa
from app.core.security.auth import Usuario, require_auth, require_roles
from app.modules.productos import service, vinculos
from app.modules.productos.schemas import (
    CupoCanalVista,
    CuposSubProducto,
    FichaSubProducto,
    Producto,
    ProductoCreate,
    ProductoUpdate,
    RestriccionesSubProducto,
    RestriccionesVista,
    SubProducto,
    SubProductoCreate,
    SubProductoUpdate,
    TipoProductoInfo,
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


def _permiso(usuario: Usuario, permiso: str) -> Usuario:
    if permiso not in usuario.permisos:
        raise problema(403, "SIN_PERMISO", "No tiene permiso para esta operacion.")
    return usuario


def _lector(usuario: Annotated[Usuario, Depends(require_roles(*_LECTURA))]) -> Usuario:
    return _permiso(usuario, "PRD-CONSULTAR")


def _administrador(
    usuario: Annotated[Usuario, Depends(require_roles(*_ESCRITURA))],
) -> Usuario:
    return _permiso(usuario, "PRD-EDITAR")


def _exportador(usuario: Annotated[Usuario, Depends(_lector)]) -> Usuario:
    return _permiso(usuario, "PRD-EXPORTAR")


Lector = Annotated[Usuario, Depends(_lector)]
Administrador = Annotated[Usuario, Depends(_administrador)]
Exportador = Annotated[Usuario, Depends(_exportador)]


@router.get(
    "",
    operation_id="PRDListar",
    response_model=list[Producto],
    openapi_extra={"x-roles": _LECTURA},
)
def listar_productos(_: Lector, conn: Db) -> list[Producto]:
    """Todos los productos (activos e inactivos) con todos sus subproductos."""
    return service.listar_productos(conn)


# Antes de /{id_producto}: si no, «tipos» se tomaría como id de producto
@router.get(
    "/tipos",
    operation_id="PRDTipos",
    response_model=list[TipoProductoInfo],
    openapi_extra={"x-roles": _LECTURA},
)
def listar_tipos(_: Lector, conn: Db) -> list[TipoProductoInfo]:
    """Tipos de producto que trae el software (no se crean desde la API)."""
    return service.listar_tipos(conn)


@router.get(
    "/subproductos/{id_sub_producto}/ficha/imprimible",
    operation_id="PRDSubFichaImprimible",
    response_model=FichaSubProducto,
    openapi_extra={
        "x-roles": _LECTURA,
        "x-permissions": ["PRD-CONSULTAR", "PRD-EXPORTAR"],
    },
)
def ficha_imprimible(
    id_sub_producto: IdPath, _: Exportador, conn: Db
) -> FichaSubProducto:
    return service.ficha_subproducto(conn, id_sub_producto)


@router.get(
    "/subproductos/{id_sub_producto}/ficha",
    operation_id="PRDSubFicha",
    response_model=FichaSubProducto,
    openapi_extra={"x-roles": _LECTURA},
)
def ficha_subproducto(id_sub_producto: IdPath, _: Lector, conn: Db) -> FichaSubProducto:
    """Lo que el asesor lee al cliente: elegibilidad, cupos, restricciones, tasas,
    comisiones, seguros y amortización, con lo heredado del producto."""
    return service.ficha_subproducto(conn, id_sub_producto)


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


@router.delete(
    "/{id_producto}",
    operation_id="PRDEliminar",
    status_code=204,
    openapi_extra={"x-roles": _ESCRITURA},
)
def eliminar_producto(
    id_producto: IdPath, request: Request, usuario: Administrador, conn: Db
) -> Response:
    """Solo un producto inactivo que nunca se usó; con uso, 409 PRODUCTO_EN_USO."""
    service.eliminar_producto(conn, id_producto, usuario, ip_cliente(request.scope))
    return Response(status_code=204)
