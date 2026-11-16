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
from app.core.security.operador import auditar, exigir_id_interno
from app.modules.catalogos import repository as catalogos_repo
from app.modules.catalogos import service as catalogos_service
from app.modules.catalogos.subproductos import PREFIJO_TIPO_TARJETA, tipo_tarjeta_de
from app.modules.productos import repository as repo
from app.modules.productos import vinculos
from app.modules.productos.schemas import (
    ComisionFicha,
    ElegibilidadFicha,
    CupoCanalVista,
    CuposSubProducto,
    FichaSubProducto,
    Producto,
    ProductoCreate,
    ProductoUpdate,
    RestriccionesSubProducto,
    RestriccionesVista,
    SeguroFicha,
    SubProducto,
    SubProductoCreate,
    SubProductoUpdate,
    TasaFicha,
    TipoProductoInfo,
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


def _validar_edades(minima: int | None, maxima: int | None) -> None:
    """E3-02 AC 5 (ASVS 2.2.1): la edad máxima no puede ser menor que la mínima."""
    if minima is not None and maxima is not None and maxima < minima:
        raise problema(
            422,
            "ELEGIBILIDAD_INVALIDA",
            "La edad máxima no puede ser menor que la mínima.",
        )


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
            if "codigo_producto" in cambios and (
                str(actual["estado"]).strip() == "A"
                or repo.producto_en_uso(conn, id_producto)
            ):
                raise problema(
                    409,
                    "PRODUCTO_NO_EDITABLE",
                    "El código solo se cambia en un producto inactivo y sin uso.",
                )
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
            _validar_edades(datos.edad_minima, datos.edad_maxima)
            id_sub = repo.insertar_subproducto(
                conn,
                id_producto,
                datos.codigo_sub_producto,
                datos.nombre_sub_producto,
                datos.edad_minima,
                datos.edad_maxima,
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
            cambios = {c: getattr(datos, c) for c in campos}
            _validar_edades(
                cambios.get("edad_minima", actual["edad_minima"]),
                cambios.get("edad_maxima", actual["edad_maxima"]),
            )
            repo.actualizar_subproducto(conn, id_sub, cambios)
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


def _subproducto_de_tipo(
    conn: Connection, id_sub: int, tipos: tuple[str, ...], que: str
) -> dict[str, Any]:
    sub = repo.obtener_subproducto(conn, id_sub)
    if sub is None:
        raise problema(404, "SUBPRODUCTO_NO_ENCONTRADO", "El subproducto no existe.")
    producto = repo.obtener_producto(conn, sub["id_producto"])
    if producto is None or producto["tipo_producto"] not in tipos:
        raise problema(
            422, "CAMPO_NO_APLICA", f"{que} no aplica a este tipo de producto."
        )
    return producto


# Cupos por canal: cuentas y tarjetas (las transacciones salen de la cuenta)
_CON_CUPOS = ("Cuenta", "Tarjeta")


def listar_cupos(conn: Connection, id_sub: int) -> list[CupoCanalVista]:
    _subproducto_de_tipo(conn, id_sub, _CON_CUPOS, "Los cupos por canal")
    return [CupoCanalVista.model_validate(f) for f in repo.listar_cupos(conn, id_sub)]


def guardar_cupos(
    conn: Connection, id_sub: int, datos: CuposSubProducto, usuario: Usuario, ip: str
) -> list[CupoCanalVista]:
    with auditar(
        "ACTUALIZAR",
        "ProductosFinancieros.ProductoCanalCupo",
        usuario,
        ip,
        f"PRD-SUB-CUPOS canales={','.join(str(c.id_canal) for c in datos.cupos)}",
        str(id_sub),
    ):
        try:
            _subproducto_de_tipo(conn, id_sub, _CON_CUPOS, "Los cupos por canal")
            if {c.id_canal for c in datos.cupos} - repo.canales_activos(conn):
                raise problema(
                    422,
                    "CANAL_NO_EXISTE",
                    "Hay canales que no existen o están inactivos.",
                )
            for c in datos.cupos:
                if (
                    c.cupo_mensual_maximo < c.cupo_diario_maximo
                    or c.monto_max_transaccion > c.cupo_diario_maximo
                ):
                    raise problema(
                        422,
                        "CUPOS_INCOHERENTES",
                        "El cupo mensual debe ser mayor o igual que el diario, y el máximo "
                        "por transacción no puede superar el diario.",
                    )
            personalizados = repo.cupos_personalizados_maximos(conn, id_sub)
            nuevos = {c.id_canal: c for c in datos.cupos}
            for id_canal, maximo in personalizados.items():
                cupo = nuevos.get(id_canal)
                # Una cuenta con cupo personalizado en ese canal quedaría por encima del
                # máximo (o sin canal): primero se ajusta la cuenta
                if (
                    cupo is None
                    or cupo.cupo_diario_maximo < maximo["cupo_diario"]
                    or cupo.cupo_mensual_maximo < maximo["cupo_mensual"]
                    or cupo.monto_max_transaccion < maximo["monto_max_transaccion"]
                ):
                    raise problema(
                        409,
                        "CUPO_MENOR_QUE_PERSONALIZADO",
                        "Hay cuentas con cupos personalizados mayores en ese canal. "
                        "Ajústalos antes de bajar o quitar el máximo.",
                    )
            repo.guardar_cupos(conn, id_sub, [c.model_dump() for c in datos.cupos])
            conn.commit()
        except DBAPIError as exc:
            conn.rollback()
            raise _traducir(exc) from None
        except Exception:
            conn.rollback()
            raise
    return [CupoCanalVista.model_validate(f) for f in repo.listar_cupos(conn, id_sub)]


def obtener_restricciones(conn: Connection, id_sub: int) -> RestriccionesVista:
    _subproducto_de_tipo(conn, id_sub, ("Cuenta",), "Las restricciones")
    return RestriccionesVista.model_validate(repo.obtener_restricciones(conn, id_sub))


def guardar_restricciones(
    conn: Connection,
    id_sub: int,
    datos: RestriccionesSubProducto,
    usuario: Usuario,
    ip: str,
) -> RestriccionesVista:
    actor = exigir_id_interno(usuario.interno())
    with auditar(
        "ACTUALIZAR",
        "ProductosFinancieros.ProductoRestriccion",
        usuario,
        ip,
        f"PRD-SUB-RESTRICCIONES sinRetiros={datos.dias_sin_retiros is not None}"
        f" saldoMinimo={datos.saldo_minimo is not None}",
        str(id_sub),
    ):
        try:
            _subproducto_de_tipo(conn, id_sub, ("Cuenta",), "Las restricciones")
            dias = datos.dias_sin_retiros
            saldo = datos.saldo_minimo
            repo.guardar_restriccion(
                conn,
                id_sub,
                "SIN_RETIROS",
                dias,
                None,
                f"Sin retiros durante {dias} días desde la apertura." if dias else "",
                actor,
            )
            repo.guardar_restriccion(
                conn,
                id_sub,
                "SALDO_MINIMO",
                None,
                saldo,
                f"Saldo mínimo de USD {saldo:,.2f}." if saldo else "",
                actor,
            )
            conn.commit()
        except DBAPIError as exc:
            conn.rollback()
            raise _traducir(exc) from None
        except Exception:
            conn.rollback()
            raise
    return RestriccionesVista.model_validate(repo.obtener_restricciones(conn, id_sub))


# ---------- Tipos, eliminación en borrador y ficha (E3-02) ----------

TIPOS_PRODUCTO = [
    TipoProductoInfo(
        codigo="Cuenta",
        nombre="Cuenta",
        descripcion="Cuentas de ahorro y corriente: cupos por canal, restricciones y tasa de ahorro.",
    ),
    TipoProductoInfo(
        codigo="Credito",
        nombre="Crédito",
        descripcion="Créditos de un tipo de crédito: tasas, seguros y tablas de amortización.",
    ),
    TipoProductoInfo(
        codigo="Tarjeta",
        nombre="Tarjeta",
        descripcion="Tarjetas de débito y crédito de una red: cupos por canal y tasas de tarjeta.",
    ),
]


def eliminar_producto(
    conn: Connection, id_producto: int, usuario: Usuario, ip: str
) -> None:
    """Solo un producto inactivo que nunca se usó (borrador). Con uso, se desactiva."""
    with auditar(
        "ELIMINAR", _TABLA_PRODUCTO, usuario, ip, "PRD-ELIMINAR", str(id_producto)
    ):
        try:
            actual = repo.obtener_producto(conn, id_producto, bloquear=True)
            if actual is None:
                raise problema(404, "PRODUCTO_NO_ENCONTRADO", "El producto no existe.")
            if str(actual["estado"]).strip() == "A":
                raise problema(
                    409,
                    "PRODUCTO_ACTIVO",
                    "Desactive el producto antes de eliminarlo.",
                )
            if repo.producto_en_uso(conn, id_producto):
                raise problema(
                    409,
                    "PRODUCTO_EN_USO",
                    "El producto tiene cuentas, tarjetas o créditos: solo se desactiva.",
                )
            repo.eliminar_producto(conn, id_producto)
            conn.commit()
        except DBAPIError as exc:
            conn.rollback()
            raise _traducir(exc) from None
        except Exception:
            conn.rollback()
            raise


def ficha_subproducto(conn: Connection, id_sub: int) -> FichaSubProducto:
    """Lo vigente del subproducto con lo que hereda del producto (solo lectura)."""
    sub = repo.obtener_subproducto(conn, id_sub)
    if sub is None:
        raise problema(404, "SUBPRODUCTO_NO_ENCONTRADO", "El subproducto no existe.")
    producto = obtener_producto(conn, sub["id_producto"])
    tipo = producto.tipo_producto
    propios = vinculos.leer(conn, "subproducto", id_sub)
    heredados = vinculos.leer(conn, "producto", producto.id_producto)
    hoy = catalogos_service.hoy()

    def origen(ids_heredados: set[Any], ids: set[Any]) -> dict[Any, bool]:
        return {i: i in ids_heredados for i in ids_heredados | ids}

    tasas_ids = origen(set(heredados["tasas_interes"]), set(propios["tasas_interes"]))
    tasas = [
        TasaFicha.model_validate({**t, "del_producto": tasas_ids[t["id_tasa_interes"]]})
        for t in catalogos_repo.listar_tasas_interes(conn, hoy)
        if t["id_tasa_interes"] in tasas_ids
    ]
    exonerados = {c["id_comision"] for c in propios["comisiones"] if c["exonerado"]}
    comisiones_ids = origen(
        {c["id_comision"] for c in heredados["comisiones"]},
        {c["id_comision"] for c in propios["comisiones"] if not c["exonerado"]},
    )
    comisiones = [
        ComisionFicha.model_validate(
            {**c, "del_producto": comisiones_ids[c["id_comision"]]}
        )
        for c in catalogos_repo.listar_comisiones(conn)
        if c["id_comision"] in comisiones_ids and c["id_comision"] not in exonerados
    ]
    obligatorio = {
        s["id_seguro"]: s["es_obligatorio"]
        for s in [*heredados["seguros"], *propios["seguros"]]
    }
    seguros_ids = origen(
        {s["id_seguro"] for s in heredados["seguros"]},
        {s["id_seguro"] for s in propios["seguros"]},
    )
    seguros = [
        SeguroFicha.model_validate(
            {
                **s,
                "es_obligatorio": obligatorio[s["id_seguro"]],
                "del_producto": seguros_ids[s["id_seguro"]],
            }
        )
        for s in catalogos_repo.listar_seguros(conn)
        if s["id_seguro"] in seguros_ids
    ]
    sistemas = sorted(
        set(heredados["sistemas_amortizacion"]) | set(propios["sistemas_amortizacion"])
    )
    cupos = (
        [
            CupoCanalVista.model_validate(c)
            for c in repo.listar_cupos(conn, id_sub)
            if c["habilitado"]
        ]
        if tipo in _CON_CUPOS
        else []
    )
    restricciones = (
        RestriccionesVista.model_validate(repo.obtener_restricciones(conn, id_sub))
        if tipo == "Cuenta"
        else None
    )
    edades = catalogos_repo.reglas_edad(conn, id_sub)
    return FichaSubProducto(
        producto=producto,
        subproducto=_subproducto(sub, tipo),
        elegibilidad=ElegibilidadFicha(
            edad_minima=edades.get("efectiva"),
            edad_maxima=edades.get("maxima"),
            edad_minima_subproducto=edades.get("subproducto"),
            edad_minima_red=edades.get("red"),
            edad_minima_politica=edades.get("politica"),
        ),
        cupos=cupos,
        restricciones=restricciones,
        tasas=tasas,
        comisiones=comisiones,
        seguros=seguros,
        sistemas_amortizacion=sistemas,
    )
