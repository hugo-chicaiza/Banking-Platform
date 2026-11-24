"""Productos y subproductos: reglas que no caben en las restricciones de la tabla.

Un producto nace Inactivo (no se ofrece hasta que el ADMIN lo activa, como el Borrador del
plan E3). Desactivar es suspender la venta: las cuentas, tarjetas y créditos que ya lo
usan siguen operando. Nada se elimina.
"""

import json
import logging
import re
from datetime import date
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import Connection
from sqlalchemy.exc import DBAPIError

from app.core.api.errors import problema, traducir_error_bd
from app.core.security import audit
from app.core.security.auth import Usuario
from app.core.security.operador import auditar, exigir_id_interno
from app.modules.catalogos import repository as catalogos_repo
from app.modules.catalogos import service as catalogos_service
from app.modules.catalogos.subproductos import PREFIJO_TIPO_TARJETA, tipo_tarjeta_de
from app.modules.productos import activacion, vinculos
from app.modules.productos import repository as repo
from app.modules.productos.schemas import (
    ComisionFicha,
    CondicionesFicha,
    CupoCanalVista,
    CuposSubProducto,
    ElegibilidadFicha,
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


def _historial(
    evento: str,
    tabla: str,
    id_: int,
    usuario: Usuario,
    ip: str,
    antes: dict[str, Any] | None,
    despues: dict[str, Any] | None,
) -> None:
    """Central audit is the only history. Correlated chunks fit its 500-char column.

    Product configuration only: no customer, account, session or credential data.
    Reassemble datos in parte order for the same evento to read the complete JSON.
    Keeps the existing best-effort audit behavior, without a schema migration.
    """
    datos = json.dumps(
        {"antes": antes, "despues": despues},
        ensure_ascii=True,
        default=str,
        separators=(",", ":"),
    )
    partes = [datos[i : i + 240] for i in range(0, len(datos), 240)]
    correlacion = uuid4().hex
    for indice, parte in enumerate(partes, 1):
        audit.registrar(
            audit.EventoAuditoria(
                accion=evento,
                tabla=tabla,
                id_registro=str(id_),
                resultado="Exitoso",
                usuario=None,
                ip=ip,
                descripcion=f"operador={usuario.id_usuario} evento={correlacion} parte={indice}/{len(partes)} datos={parte}",
                roles=usuario.roles_texto(),
            )
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
        f"PRD_PRODUCTO_CREADO codigo={datos.codigo_producto} tipo={datos.tipo_producto}",
    ) as registro:
        try:
            _verificar_referencias(conn, datos)
            valores = datos.model_dump()
            tipos = repo.listar_tipos(conn)
            candidatos = [
                t
                for t in tipos
                if t["tipo_producto"] == datos.tipo_producto
                and (
                    datos.tipo_producto != "Cuenta"
                    or t["tipo_cuenta"] == datos.tipo_cuenta
                )
                and (
                    datos.id_tipo_producto is None
                    or t["id_tipo_producto"] == datos.id_tipo_producto
                )
            ]
            if not candidatos:
                raise problema(
                    422,
                    "TIPO_PRODUCTO_INVALIDO",
                    "El tipo de producto no existe o no corresponde a los datos.",
                )
            valores["id_tipo_producto"] = candidatos[0]["id_tipo_producto"]
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
            despues = repo.obtener_producto(conn, id_producto)
            conn.commit()
            _historial(
                "PRD_PRODUCTO_CREADO",
                _TABLA_PRODUCTO,
                id_producto,
                usuario,
                ip,
                None,
                despues,
            )
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
        f"PRD_PRODUCTO_EDITADO campos={','.join(campos)}",
        str(id_producto),
    ):
        try:
            actual = repo.obtener_producto(conn, id_producto, bloquear=True)
            if actual is None:
                raise problema(404, "PRODUCTO_NO_ENCONTRADO", "El producto no existe.")
            cambios = {c: getattr(datos, c) for c in campos}
            _sincronizar_estado(actual, cambios)
            _reglas_de_estado(conn, actual, cambios, id_producto=id_producto)
            if set(cambios) - {"estado", "estado_catalogo"} and (
                actual.get("estado_catalogo", "Borrador") != "Borrador"
                or str(actual["estado"]).strip() == "A"
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
            _exigir_flujo_estado(actual, cambios)
            repo.actualizar_producto(conn, id_producto, cambios)
            despues = repo.obtener_producto(conn, id_producto)
            conn.commit()
            _historial(
                "PRD_PRODUCTO_EDITADO",
                _TABLA_PRODUCTO,
                id_producto,
                usuario,
                ip,
                actual,
                despues,
            )
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
            _validar_requerido(conn, datos.id_sub_producto_requerido)
            id_sub = repo.insertar_subproducto(
                conn,
                id_producto,
                datos.codigo_sub_producto,
                datos.nombre_sub_producto,
                datos.edad_minima,
                datos.edad_maxima,
                tipo_cliente_permitido=datos.tipo_cliente_permitido,
                requiere_tutor=datos.requiere_tutor,
                id_sub_producto_requerido=datos.id_sub_producto_requerido,
                maximo_por_cliente=datos.maximo_por_cliente,
            )
            registro.id_registro = str(id_sub)
            despues = repo.obtener_subproducto(conn, id_sub)
            conn.commit()
            _historial(
                "PRD_SUBPRODUCTO_EDITADO",
                _TABLA_SUBPRODUCTO,
                id_sub,
                usuario,
                ip,
                None,
                despues,
            )
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
        f"PRD_SUBPRODUCTO_EDITADO campos={','.join(campos)}",
        str(id_sub),
    ):
        try:
            actual = repo.obtener_subproducto(conn, id_sub, bloquear=True)
            if actual is None:
                raise problema(
                    404, "SUBPRODUCTO_NO_ENCONTRADO", "El subproducto no existe."
                )
            cambios = {c: getattr(datos, c) for c in campos}
            _sincronizar_estado(actual, cambios)
            _reglas_de_estado(conn, actual, cambios, id_sub=id_sub)
            _exigir_flujo_estado(actual, cambios)
            if (
                set(cambios) - {"estado", "estado_catalogo"}
                and actual.get("estado_catalogo", "Borrador") != "Borrador"
            ):
                raise problema(
                    409,
                    "PRODUCTO_NO_EDITABLE",
                    "Los datos solo se cambian en Borrador.",
                )
            _validar_requerido(conn, cambios.get("id_sub_producto_requerido"), id_sub)
            _validar_edades(
                cambios.get("edad_minima", actual["edad_minima"]),
                cambios.get("edad_maxima", actual["edad_maxima"]),
            )
            repo.actualizar_subproducto(conn, id_sub, cambios)
            despues = repo.obtener_subproducto(conn, id_sub)
            conn.commit()
            _historial(
                "PRD_SUBPRODUCTO_EDITADO",
                _TABLA_SUBPRODUCTO,
                id_sub,
                usuario,
                ip,
                actual,
                despues,
            )
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


def listar_tipos(conn: Connection) -> list[TipoProductoInfo]:
    return [TipoProductoInfo.model_validate(t) for t in repo.listar_tipos(conn)]


def _reglas_de_estado(
    conn: Connection,
    actual: dict[str, Any],
    cambios: dict[str, Any],
    id_sub: int | None = None,
    id_producto: int | None = None,
) -> None:
    """E3-06: activar exige la lista completa; retirar, que no queden cuentas abiertas."""
    nuevo = cambios.get("estado_catalogo")
    if nuevo is None or nuevo == actual.get("estado_catalogo"):
        return
    if nuevo == "Activo" and id_sub is not None:
        activacion.exigir_activacion(conn, id_sub)
    if nuevo == "Retirado":
        activacion.exigir_retiro(conn, id_sub=id_sub, id_producto=id_producto)


def _sincronizar_estado(actual: dict[str, Any], cambios: dict[str, Any]) -> None:
    estado = cambios.get("estado_catalogo")
    if estado is None and "estado" in cambios:
        estado = "Activo" if cambios["estado"] == "A" else "Suspendido"
    if estado is None:
        return
    anterior = actual.get("estado_catalogo") or (
        "Activo" if actual["estado"] == "A" else "Suspendido"
    )
    transiciones = {
        "Borrador": {"Activo"},
        "Activo": {"Suspendido", "Retirado"},
        "Suspendido": {"Activo", "Retirado"},
        "Retirado": set(),
    }
    if estado != anterior and estado not in transiciones[anterior]:
        raise problema(
            409, "ESTADO_INVALIDO", "La transicion de estado no esta permitida."
        )
    legado = "A" if estado == "Activo" else "I"
    if "estado" in cambios and cambios["estado"] != legado:
        raise problema(
            422, "ESTADO_INVALIDO", "Los estados enviados son incompatibles."
        )
    cambios.update(estado=legado, estado_catalogo=estado)


def _exigir_flujo_estado(actual: dict[str, Any], cambios: dict[str, Any]) -> None:
    destino = cambios.get("estado_catalogo")
    if destino is not None and destino != actual.get("estado_catalogo"):
        raise problema(
            409, "APROBACION_REQUERIDA", "Solicite el cambio de estado para aprobación."
        )


def _validar_requerido(
    conn: Connection, requerido: int | None, id_sub: int | None = None
) -> None:
    if requerido is not None and (
        requerido == id_sub or repo.obtener_subproducto(conn, requerido) is None
    ):
        raise problema(
            422,
            "ELEGIBILIDAD_INVALIDA",
            "El subproducto requerido no existe o es el mismo.",
        )


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
            if (
                str(actual["estado"]).strip() == "A"
                or actual.get("estado_catalogo", "Borrador") != "Borrador"
            ):
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
        if t["id_tasa_interes"] in tasas_ids and t["vigente"]
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
        fecha=hoy,
        condiciones=(
            CondicionesFicha.model_validate(c)
            if (c := repo.condiciones_vigentes(conn, id_sub, hoy, "FICHA")) is not None
            else None
        ),
        elegibilidad=ElegibilidadFicha(
            tipo_cliente_permitido=sub.get("tipo_cliente_permitido", "Ambos"),
            requiere_tutor=sub.get("requiere_tutor", False),
            id_sub_producto_requerido=sub.get("id_sub_producto_requerido"),
            maximo_por_cliente=sub.get("maximo_por_cliente"),
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


# ---------- E3-01: servicios internos sin rutas nuevas ----------


def condiciones_vigentes(
    conn: Connection, id_subproducto: int, fecha_contable: date, canal: str
) -> dict[str, Any] | None:
    return repo.condiciones_vigentes(conn, id_subproducto, fecha_contable, canal)


def cupo_vigente(
    conn: Connection, id_subproducto: int, fecha_contable: date, canal: str
) -> dict[str, Any]:
    return repo.cupo_vigente(conn, id_subproducto, fecha_contable, canal)


def restricciones_vigentes(
    conn: Connection, id_subproducto: int, fecha_contable: date, canal: str
) -> list[dict[str, Any]]:
    return repo.restricciones_vigentes(conn, id_subproducto, fecha_contable, canal)


# ---------- E3-01: elegibilidad previa a contratación ----------


def cliente_elegible(
    conn: Connection,
    id_cliente: int,
    id_subproducto: int,
    fecha_contable: date | None = None,
    *,
    apertura_cuenta: bool = False,
) -> tuple[bool, list[str]]:
    """Evalúa elegibilidad sin modificar datos; rechaza cuando falta prueba de tutor."""
    if id_cliente <= 0 or id_subproducto <= 0:
        raise ValueError("Los identificadores deben ser positivos")
    fecha = fecha_contable or catalogos_service.hoy()
    if not isinstance(fecha, date):
        raise TypeError("fecha_contable debe ser date")
    datos = repo.datos_elegibilidad(conn, id_cliente, id_subproducto)
    if datos is None:
        return False, ["CLIENTE_O_SUBPRODUCTO_NO_EXISTE"]

    motivos: list[str] = []
    if datos["estado_cliente"] != "Activo":
        motivos.append("CLIENTE_NO_ACTIVO")
    if (
        datos["estado_producto"] != "A"
        or datos["estado_producto_nuevo"] != "Activo"
        or datos["estado_subproducto"] != "A"
        or datos["estado_subproducto_nuevo"] != "Activo"
    ):
        motivos.append("PRODUCTO_NO_ACTIVO")

    permitido = str(datos["tipo_permitido"]).strip().casefold()
    tipo = str(datos["tipo_cliente"]).strip().casefold()
    if permitido not in ("ambos", tipo):
        motivos.append("TIPO_CLIENTE_NO_PERMITIDO")

    if tipo == "natural":
        nacimiento = datos["fecha_nacimiento"]
        if nacimiento is None or nacimiento > fecha:
            motivos.append("FECHA_NACIMIENTO_NO_VALIDA")
        else:
            edad = (
                fecha.year
                - nacimiento.year
                - ((fecha.month, fecha.day) < (nacimiento.month, nacimiento.day))
            )
            if datos["edad_minima"] is not None and edad < datos["edad_minima"]:
                motivos.append("EDAD_INFERIOR_MINIMA")
            if datos["edad_maxima"] is not None and edad > datos["edad_maxima"]:
                motivos.append("EDAD_SUPERIOR_MAXIMA")
            if apertura_cuenta and edad < 18:
                motivos.append("TUTOR_NO_VERIFICABLE")
    elif datos["edad_minima"] is not None or datos["edad_maxima"] is not None:
        motivos.append("EDAD_NO_APLICA_A_PERSONA_JURIDICA")

    # No hay una relación cliente-tutor verificable en el esquema recibido.
    # Rechazar antes que asumir que existe un tutor válido.
    if datos["requiere_tutor"] and "TUTOR_NO_VERIFICABLE" not in motivos:
        motivos.append("TUTOR_NO_VERIFICABLE")
    if apertura_cuenta and tipo == "juridico":
        motivos.append("REPRESENTANTE_NO_VERIFICABLE")

    cuentas = repo.cuentas_cliente_para_elegibilidad(conn, id_cliente)
    tarjetas = repo.tarjetas_cliente_para_elegibilidad(conn, id_cliente)
    activas = [c for c in cuentas if c["estado"] == "Activa"]
    tarjetas_vigentes = [t for t in tarjetas if t["estado"] in ("Aprobada", "Generada")]
    requerido = datos["id_requerido"]
    if requerido is not None and not any(
        item["id_subproducto"] == requerido for item in [*activas, *tarjetas_vigentes]
    ):
        motivos.append("PRODUCTO_REQUERIDO_NO_CONTRATADO")
    if datos["tipo_producto"] == "Tarjeta" and not activas:
        motivos.append("TARJETA_REQUIERE_CUENTA_ACTIVA")
    maximo: int | None = (
        None
        if datos["maximo_por_cliente"] is None
        else int(datos["maximo_por_cliente"])
    )
    if datos["tipo_producto"] == "Cuenta":
        limites: list[int] = [
            int(r["cantidad"])
            for r in repo.restricciones_vigentes(
                conn, id_subproducto, fecha, "ELEGIBILIDAD"
            )
            if r["tipo_restriccion"] == "MAXIMO_CUENTAS_CLIENTE"
            and r.get("cantidad") is not None
        ]
        if limites:
            maximo = min(limites) if maximo is None else min(maximo, min(limites))
    if maximo is not None:
        cuentas_computables = activas
        if datos["tipo_producto"] == "Cuenta":
            cuentas_computables = [
                c for c in cuentas if c["estado"] not in ("Cerrada", "Anulada")
            ]
        cantidad = sum(
            item["id_subproducto"] == id_subproducto
            for item in [*cuentas_computables, *tarjetas_vigentes]
        )
        if cantidad >= maximo:
            motivos.append("MAXIMO_POR_CLIENTE_ALCANZADO")
    return not motivos, motivos
