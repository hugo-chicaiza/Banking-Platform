"""Productos y subproductos: reglas que no caben en las restricciones de la tabla.

Un producto nace Inactivo (no se ofrece hasta que el ADMIN lo activa, como el Borrador del
plan E3). Desactivar es suspender la venta: las cuentas, tarjetas y créditos que ya lo
usan siguen operando. Nada se elimina.
"""

import logging
import re
from typing import Any

from fastapi import HTTPException
from sqlalchemy import Connection
from sqlalchemy.exc import DBAPIError

from app.core.api.errors import problema, traducir_error_bd
from app.core.security.auth import Usuario
from app.core.security.operador import auditar
from app.modules.catalogos.subproductos import PREFIJO_TIPO_TARJETA, tipo_tarjeta_de
from app.modules.productos import repository as repo
from app.modules.productos.schemas import (
    Producto,
    ProductoCreate,
    ProductoUpdate,
    SubProducto,
    SubProductoCreate,
    SubProductoUpdate,
)

logger = logging.getLogger(__name__)
_TABLA_PRODUCTO = "ProductosFinancieros.Producto"
_TABLA_SUBPRODUCTO = "ProductosFinancieros.SubProducto"
_RESTRICCION = re.compile(
    r"'(UQ_Producto_Codigo|UQ_SubProducto_Codigo|UQ_SubProducto_SubProducto_Producto)'"
)


def _no_leido() -> HTTPException:
    """El registro recién guardado no se pudo releer: el cambio ya se confirmó, se informa sin datos."""
    logger.error("productos: registro guardado no encontrado al releerlo")
    return problema(500, "ERROR_INTERNO", "Error interno del servidor.")


def _traducir(exc: DBAPIError) -> HTTPException:
    if _RESTRICCION.search(str(exc.orig)):
        return problema(
            409, "CODIGO_DUPLICADO", "Ya existe un registro con ese código."
        )
    return traducir_error_bd(exc)


def _subproducto(fila: dict[str, Any], tipo_producto: str) -> SubProducto:
    fila = {**fila, "estado": str(fila["estado"]).rstrip()}
    fila["tipo_tarjeta"] = (
        tipo_tarjeta_de(fila["codigo_sub_producto"])
        if tipo_producto == "Tarjeta"
        else None
    )
    return SubProducto.model_validate(fila)


def _producto(fila: dict[str, Any], subproductos: list[dict[str, Any]]) -> Producto:
    datos = {**fila, "estado": str(fila["estado"]).rstrip()}
    datos["subproductos"] = [
        _subproducto(s, fila["tipo_producto"]) for s in subproductos
    ]
    return Producto.model_validate(datos)


def listar_productos(conn: Connection) -> list[Producto]:
    por_producto: dict[int, list[dict[str, Any]]] = {}
    for sub in repo.listar_subproductos(conn):
        por_producto.setdefault(sub["id_producto"], []).append(sub)
    return [
        _producto(p, por_producto.get(p["id_producto"], []))
        for p in repo.listar_productos(conn)
    ]


def obtener_producto(conn: Connection, id_producto: int) -> Producto:
    fila = repo.obtener_producto(conn, id_producto)
    if fila is None:
        raise problema(404, "PRODUCTO_NO_ENCONTRADO", "El producto no existe.")
    return _producto(fila, repo.listar_subproductos(conn, id_producto))


def _verificar_referencias(conn: Connection, datos: ProductoCreate) -> None:
    if datos.id_tipo_credito is not None and not repo.existe_tipo_credito_activo(
        conn, datos.id_tipo_credito
    ):
        raise problema(
            422,
            "TIPO_CREDITO_NO_EXISTE",
            "El tipo de crédito no existe o está inactivo.",
        )
    if datos.id_red is not None and not repo.existe_red_activa(conn, datos.id_red):
        raise problema(
            422, "RED_NO_EXISTE", "La red de tarjetas no existe o está inactiva."
        )


def crear_producto(
    conn: Connection, datos: ProductoCreate, usuario: Usuario, ip: str
) -> Producto:
    with auditar(
        "CREAR",
        _TABLA_PRODUCTO,
        usuario,
        ip,
        f"PRD-CREAR codigo={datos.codigo_producto} tipo={datos.tipo_producto}",
    ) as registro:
        try:
            _verificar_referencias(conn, datos)
            valores = datos.model_dump()
            if (
                datos.tipo_producto == "Cuenta"
                and valores["monto_apertura_minimo"] is None
            ):
                valores["monto_apertura_minimo"] = 0
            elif datos.tipo_producto != "Cuenta":
                valores["monto_apertura_minimo"] = (
                    0  # default de la tabla; no aplica fuera de Cuenta
                )
            id_producto = repo.insertar_producto(conn, valores)
            registro.id_registro = str(id_producto)
            conn.commit()
        except DBAPIError as exc:
            conn.rollback()
            raise _traducir(exc) from None
        except Exception:
            conn.rollback()
            raise
    return obtener_producto(conn, id_producto)


def actualizar_producto(
    conn: Connection, id_producto: int, datos: ProductoUpdate, usuario: Usuario, ip: str
) -> Producto:
    campos = sorted(datos.model_fields_set)
    with auditar(
        "ACTUALIZAR",
        _TABLA_PRODUCTO,
        usuario,
        ip,
        f"PRD-EDITAR campos={','.join(campos)}",
        str(id_producto),
    ):
        try:
            actual = repo.obtener_producto(conn, id_producto, bloquear=True)
            if actual is None:
                raise problema(404, "PRODUCTO_NO_ENCONTRADO", "El producto no existe.")
            cambios = {c: getattr(datos, c) for c in campos}
            if (
                "monto_apertura_minimo" in cambios
                and actual["tipo_producto"] != "Cuenta"
            ):
                raise problema(
                    422,
                    "CAMPO_NO_APLICA",
                    "El monto mínimo de apertura solo aplica a productos Cuenta.",
                )
            if cambios.get("estado") == "A" and not repo.listar_subproductos(
                conn, id_producto
            ):
                raise problema(
                    409,
                    "PRODUCTO_SIN_SUBPRODUCTOS",
                    "Agregue al menos un subproducto antes de activar el producto.",
                )
            repo.actualizar_producto(conn, id_producto, cambios)
            conn.commit()
        except DBAPIError as exc:
            conn.rollback()
            raise _traducir(exc) from None
        except Exception:
            conn.rollback()
            raise
    return obtener_producto(conn, id_producto)


def crear_subproducto(
    conn: Connection,
    id_producto: int,
    datos: SubProductoCreate,
    usuario: Usuario,
    ip: str,
) -> SubProducto:
    with auditar(
        "CREAR",
        _TABLA_SUBPRODUCTO,
        usuario,
        ip,
        f"PRD-SUB-CREAR producto={id_producto} codigo={datos.codigo_sub_producto}",
    ) as registro:
        try:
            producto = repo.obtener_producto(conn, id_producto, bloquear=True)
            if producto is None:
                raise problema(404, "PRODUCTO_NO_ENCONTRADO", "El producto no existe.")
            # Convención de la emisión (subproductos.py): el prefijo dice si es débito o crédito
            if (
                producto["tipo_producto"] == "Tarjeta"
                and tipo_tarjeta_de(datos.codigo_sub_producto) is None
            ):
                prefijos = " o ".join(PREFIJO_TIPO_TARJETA)
                raise problema(
                    422,
                    "CODIGO_TARJETA_INVALIDO",
                    f"El código de un subproducto de tarjeta debe empezar por {prefijos}.",
                )
            id_sub = repo.insertar_subproducto(
                conn, id_producto, datos.codigo_sub_producto, datos.nombre_sub_producto
            )
            registro.id_registro = str(id_sub)
            conn.commit()
        except DBAPIError as exc:
            conn.rollback()
            raise _traducir(exc) from None
        except Exception:
            conn.rollback()
            raise
    fila = repo.obtener_subproducto(conn, id_sub)
    if fila is None:
        raise _no_leido()
    return _subproducto(fila, producto["tipo_producto"])


def actualizar_subproducto(
    conn: Connection, id_sub: int, datos: SubProductoUpdate, usuario: Usuario, ip: str
) -> SubProducto:
    campos = sorted(datos.model_fields_set)
    with auditar(
        "ACTUALIZAR",
        _TABLA_SUBPRODUCTO,
        usuario,
        ip,
        f"PRD-SUB-EDITAR campos={','.join(campos)}",
        str(id_sub),
    ):
        try:
            actual = repo.obtener_subproducto(conn, id_sub, bloquear=True)
            if actual is None:
                raise problema(
                    404, "SUBPRODUCTO_NO_ENCONTRADO", "El subproducto no existe."
                )
            repo.actualizar_subproducto(
                conn, id_sub, {c: getattr(datos, c) for c in campos}
            )
            conn.commit()
        except DBAPIError as exc:
            conn.rollback()
            raise _traducir(exc) from None
        except Exception:
            conn.rollback()
            raise
    fila = repo.obtener_subproducto(conn, id_sub)
    producto = repo.obtener_producto(conn, actual["id_producto"])
    if fila is None or producto is None:
        raise _no_leido()
    return _subproducto(fila, producto["tipo_producto"])
