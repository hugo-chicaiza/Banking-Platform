"""Vínculos uno a varios de productos y subproductos con tasas, comisiones, seguros y
sistemas de amortización (migración 20261117_tasas_y_vinculos).

Un vínculo del producto aplica a todos sus subproductos; uno del subproducto lo
personaliza. Una comisión vinculada al subproducto con exonerado=1 indica que ese
subproducto no la cobra aunque el producto sí. Por ahora solo se guarda el checklist:
el cobro y la elección de tasa los aplicará cada módulo después.

Desmarcar no borra: la fila queda en Estado 'I' (historial) y marcar de nuevo la reactiva.
Un vínculo con un objeto desactivado en Catálogos (tasa, comisión, seguro o sistema) no
cuenta: no se muestra, no se aplica y al guardar el checklist se desmarca.
El SQL de cada tabla es fijo.
"""

from contextlib import ExitStack
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError

from app.core.api.errors import problema, traducir_error_bd
from app.core.security.auth import Usuario
from app.core.security.operador import auditar, exigir_id_interno
from app.modules.productos import repository as repo
from app.modules.productos.schemas import VinculosEntrada, VinculosVista

Destino = Literal["producto", "subproducto"]

# Qué tasas acepta cada tipo de producto
_TASAS_POR_TIPO = {
    "Credito": {"CREDITO"},
    "Cuenta": {"AHORRO"},
    "Tarjeta": {
        "TARJETA_COMPRA",
        "TARJETA_AVANCE",
        "TARJETA_DIFERIDO",
        "TARJETA_EXTERIOR",
        "TARJETA_MORA",
    },
}


@dataclass(frozen=True)
class _Tabla:
    listar: str
    desactivar: str
    guardar: str


# Literales completos (sin armar nombres de tabla): Bandit B608
_TABLAS = {
    "tasas": _Tabla(
        listar="""
            SELECT v.IdTasaInteres AS objeto
            FROM ProductosFinancieros.ProductoTasaInteres AS v
            JOIN Credito.TasaInteres AS o ON o.IdTasaInteres = v.IdTasaInteres AND o.Estado = 'A'
            WHERE v.Estado = 'A'
              AND ISNULL(v.IdProducto, 0) = ISNULL(:id_producto, 0)
              AND ISNULL(v.IdSubProducto, 0) = ISNULL(:id_sub, 0)
            ORDER BY v.IdTasaInteres
        """,
        desactivar="""
            UPDATE ProductosFinancieros.ProductoTasaInteres SET Estado = 'I'
            WHERE Estado = 'A'
              AND ISNULL(IdProducto, 0) = ISNULL(:id_producto, 0)
              AND ISNULL(IdSubProducto, 0) = ISNULL(:id_sub, 0)
        """,
        guardar="""
            MERGE ProductosFinancieros.ProductoTasaInteres WITH (HOLDLOCK) AS d
            USING (SELECT :objeto AS IdTasaInteres) AS o
               ON d.IdTasaInteres = o.IdTasaInteres
              AND ISNULL(d.IdProducto, 0) = ISNULL(:id_producto, 0)
              AND ISNULL(d.IdSubProducto, 0) = ISNULL(:id_sub, 0)
            WHEN MATCHED THEN UPDATE SET Estado = 'A', AsignadoPor = :usuario,
                FechaAsignacion = SYSUTCDATETIME()
            WHEN NOT MATCHED THEN INSERT (IdTasaInteres, IdProducto, IdSubProducto, AsignadoPor)
                VALUES (:objeto, :id_producto, :id_sub, :usuario);
        """,
    ),
    "comisiones": _Tabla(
        listar="""
            SELECT v.IdComision AS objeto, v.Exonerado AS marca
            FROM ProductosFinancieros.ProductoComision AS v
            JOIN Transacciones.Comisiones AS o ON o.IdComision = v.IdComision AND o.Estado = 'A'
            WHERE v.Estado = 'A'
              AND ISNULL(v.IdProducto, 0) = ISNULL(:id_producto, 0)
              AND ISNULL(v.IdSubProducto, 0) = ISNULL(:id_sub, 0)
            ORDER BY v.IdComision
        """,
        desactivar="""
            UPDATE ProductosFinancieros.ProductoComision SET Estado = 'I'
            WHERE Estado = 'A'
              AND ISNULL(IdProducto, 0) = ISNULL(:id_producto, 0)
              AND ISNULL(IdSubProducto, 0) = ISNULL(:id_sub, 0)
        """,
        guardar="""
            MERGE ProductosFinancieros.ProductoComision WITH (HOLDLOCK) AS d
            USING (SELECT :objeto AS IdComision) AS o
               ON d.IdComision = o.IdComision
              AND ISNULL(d.IdProducto, 0) = ISNULL(:id_producto, 0)
              AND ISNULL(d.IdSubProducto, 0) = ISNULL(:id_sub, 0)
            WHEN MATCHED THEN UPDATE SET Estado = 'A', Exonerado = :marca,
                AsignadoPor = :usuario, FechaAsignacion = SYSUTCDATETIME()
            WHEN NOT MATCHED THEN INSERT (IdComision, IdProducto, IdSubProducto, Exonerado,
                AsignadoPor)
                VALUES (:objeto, :id_producto, :id_sub, :marca, :usuario);
        """,
    ),
    "seguros": _Tabla(
        listar="""
            SELECT v.IdSeguro AS objeto, v.EsObligatorio AS marca
            FROM ProductosFinancieros.ProductoSeguro AS v
            JOIN Credito.Seguro AS o ON o.IdSeguro = v.IdSeguro AND o.Estado = 'A'
            WHERE v.Estado = 'A'
              AND ISNULL(v.IdProducto, 0) = ISNULL(:id_producto, 0)
              AND ISNULL(v.IdSubProducto, 0) = ISNULL(:id_sub, 0)
            ORDER BY v.IdSeguro
        """,
        desactivar="""
            UPDATE ProductosFinancieros.ProductoSeguro SET Estado = 'I'
            WHERE Estado = 'A'
              AND ISNULL(IdProducto, 0) = ISNULL(:id_producto, 0)
              AND ISNULL(IdSubProducto, 0) = ISNULL(:id_sub, 0)
        """,
        guardar="""
            MERGE ProductosFinancieros.ProductoSeguro WITH (HOLDLOCK) AS d
            USING (SELECT :objeto AS IdSeguro) AS o
               ON d.IdSeguro = o.IdSeguro
              AND ISNULL(d.IdProducto, 0) = ISNULL(:id_producto, 0)
              AND ISNULL(d.IdSubProducto, 0) = ISNULL(:id_sub, 0)
            WHEN MATCHED THEN UPDATE SET Estado = 'A', EsObligatorio = :marca,
                AsignadoPor = :usuario, FechaAsignacion = SYSUTCDATETIME()
            WHEN NOT MATCHED THEN INSERT (IdSeguro, IdProducto, IdSubProducto, EsObligatorio,
                AsignadoPor)
                VALUES (:objeto, :id_producto, :id_sub, :marca, :usuario);
        """,
    ),
    "sistemas": _Tabla(
        listar="""
            SELECT v.CodigoSistema AS objeto
            FROM ProductosFinancieros.ProductoSistemaAmortizacion AS v
            JOIN Catalogo.SistemaAmortizacion AS o ON o.Codigo = v.CodigoSistema AND o.Estado = 'A'
            WHERE v.Estado = 'A'
              AND ISNULL(v.IdProducto, 0) = ISNULL(:id_producto, 0)
              AND ISNULL(v.IdSubProducto, 0) = ISNULL(:id_sub, 0)
            ORDER BY v.CodigoSistema
        """,
        desactivar="""
            UPDATE ProductosFinancieros.ProductoSistemaAmortizacion SET Estado = 'I'
            WHERE Estado = 'A'
              AND ISNULL(IdProducto, 0) = ISNULL(:id_producto, 0)
              AND ISNULL(IdSubProducto, 0) = ISNULL(:id_sub, 0)
        """,
        guardar="""
            MERGE ProductosFinancieros.ProductoSistemaAmortizacion WITH (HOLDLOCK) AS d
            USING (SELECT :objeto AS CodigoSistema) AS o
               ON d.CodigoSistema = o.CodigoSistema
              AND ISNULL(d.IdProducto, 0) = ISNULL(:id_producto, 0)
              AND ISNULL(d.IdSubProducto, 0) = ISNULL(:id_sub, 0)
            WHEN MATCHED THEN UPDATE SET Estado = 'A', AsignadoPor = :usuario,
                FechaAsignacion = SYSUTCDATETIME()
            WHEN NOT MATCHED THEN INSERT (CodigoSistema, IdProducto, IdSubProducto, AsignadoPor)
                VALUES (:objeto, :id_producto, :id_sub, :usuario);
        """,
    ),
}


def _ids(destino: Destino, id_: int) -> dict[str, int | None]:
    return {
        "id_producto": id_ if destino == "producto" else None,
        "id_sub": id_ if destino == "subproducto" else None,
    }


def leer(conn: Connection, destino: Destino, id_: int) -> dict[str, Any]:
    ids = _ids(destino, id_)
    filas = {
        clave: [dict(r) for r in conn.execute(text(t.listar), ids).mappings()]
        for clave, t in _TABLAS.items()
    }
    return {
        "tasas_interes": [int(f["objeto"]) for f in filas["tasas"]],
        "comisiones": [
            {"id_comision": int(f["objeto"]), "exonerado": bool(f["marca"])}
            for f in filas["comisiones"]
        ],
        "seguros": [
            {"id_seguro": int(f["objeto"]), "es_obligatorio": bool(f["marca"])}
            for f in filas["seguros"]
        ],
        "sistemas_amortizacion": [str(f["objeto"]) for f in filas["sistemas"]],
    }


# Tabla que se registra en Auditoria.Auditoria por cada lista que cambia
_TABLA_AUDITORIA = {
    "tasas": "ProductosFinancieros.ProductoTasaInteres",
    "comisiones": "ProductosFinancieros.ProductoComision",
    "seguros": "ProductosFinancieros.ProductoSeguro",
    "sistemas": "ProductosFinancieros.ProductoSistemaAmortizacion",
}


def _por_tabla_entrada(datos: VinculosEntrada) -> dict[str, dict[Any, Any]]:
    """Cada lista como {objeto: marca} (marca = exonerado u obligatorio)."""
    return {
        "tasas": {t: None for t in datos.tasas_interes},
        "comisiones": {c.id_comision: c.exonerado for c in datos.comisiones},
        "seguros": {s.id_seguro: s.es_obligatorio for s in datos.seguros},
        "sistemas": {s: None for s in datos.sistemas_amortizacion},
    }


def _por_tabla_leido(leido: dict[str, Any]) -> dict[str, dict[Any, Any]]:
    return {
        "tasas": {t: None for t in leido["tasas_interes"]},
        "comisiones": {c["id_comision"]: c["exonerado"] for c in leido["comisiones"]},
        "seguros": {s["id_seguro"]: s["es_obligatorio"] for s in leido["seguros"]},
        "sistemas": {s: None for s in leido["sistemas_amortizacion"]},
    }


def _detalle(
    destino: Destino, id_: int, antes: dict[Any, Any], despues: dict[Any, Any]
) -> str:
    """Solo ids: qué se marcó, qué se desmarcó y a qué se le cambió la marca."""
    marcados = sorted(str(k) for k in despues.keys() - antes.keys())
    quitados = sorted(str(k) for k in antes.keys() - despues.keys())
    cambiados = sorted(
        f"{k}={int(bool(despues[k]))}"
        for k in despues.keys() & antes.keys()
        if despues[k] != antes[k]
    )
    partes = [f"PRD-VINCULOS {destino}={id_}"]
    if marcados:
        partes.append(f"marcados={','.join(marcados)}")
    if quitados:
        partes.append(f"desmarcados={','.join(quitados)}")
    if cambiados:
        partes.append(f"marca={','.join(cambiados)}")
    return " ".join(partes)[:250]


def _guardar(
    conn: Connection,
    destino: Destino,
    id_: int,
    datos: VinculosEntrada,
    usuario: int,
    tablas: list[str],
) -> None:
    """Escribe solo las listas que cambian (las demás conservan su fecha de asignación)."""
    ids = _ids(destino, id_)
    listas = _por_tabla_entrada(datos)
    for clave in tablas:
        tabla = _TABLAS[clave]
        conn.execute(text(tabla.desactivar), ids)
        for objeto, marca in listas[clave].items():
            conn.execute(
                text(tabla.guardar),
                {**ids, "objeto": objeto, "marca": marca, "usuario": usuario},
            )


def _validar(
    conn: Connection, producto: dict[str, Any], destino: Destino, datos: VinculosEntrada
) -> None:
    tipo = producto["tipo_producto"]
    tasas = _filas(
        conn,
        """
        SELECT IdTasaInteres AS id, TipoTasa AS tipo, IdTipoCredito AS tipo_credito,
               MontoMinimo AS minimo, MontoMaximo AS maximo,
               VigenciaDesde AS desde, VigenciaHasta AS hasta
        FROM Credito.TasaInteres
        WHERE Estado = 'A' AND IdTasaInteres IN (SELECT value FROM OPENJSON(:ids))
        """,
        datos.tasas_interes,
    )
    if len(tasas) != len(datos.tasas_interes) or any(
        t["tipo"] not in _TASAS_POR_TIPO[tipo]
        or (tipo == "Credito" and t["tipo_credito"] != producto["id_tipo_credito"])
        for t in tasas
    ):
        raise problema(
            422,
            "TASA_NO_APLICA",
            "Hay tasas inactivas o que no corresponden a este tipo de producto.",
        )
    # Varias tasas de crédito del catálogo pueden cruzarse; las vinculadas a un mismo
    # producto o subproducto no: la simulación y la evaluación exigen una sola
    credito = [t for t in tasas if t["tipo"] == "CREDITO"]
    for i, a in enumerate(credito):
        for b in credito[i + 1 :]:
            if _se_solapan(a, b):
                raise problema(
                    422,
                    "TASAS_SOLAPADAS",
                    "Dos tasas de crédito vinculadas se cruzan en monto y fechas: "
                    "deja solo una para cada rango.",
                )
    comisiones = [c.id_comision for c in datos.comisiones]
    if len(
        _filas(
            conn,
            "SELECT IdComision AS id FROM Transacciones.Comisiones"
            " WHERE Estado = 'A' AND IdComision IN (SELECT value FROM OPENJSON(:ids))",
            comisiones,
        )
    ) != len(comisiones):
        raise problema(
            422,
            "COMISION_NO_EXISTE",
            "Hay comisiones que no existen o están inactivas.",
        )
    if destino == "producto" and any(c.exonerado for c in datos.comisiones):
        raise problema(
            422,
            "CAMPO_NO_APLICA",
            "La exoneración se marca en un subproducto, no en el producto.",
        )
    seguros = [s.id_seguro for s in datos.seguros]
    if len(
        _filas(
            conn,
            "SELECT IdSeguro AS id FROM Credito.Seguro"
            " WHERE Estado = 'A' AND IdSeguro IN (SELECT value FROM OPENJSON(:ids))",
            seguros,
        )
    ) != len(seguros):
        raise problema(
            422, "SEGURO_NO_EXISTE", "Hay seguros que no existen o están inactivos."
        )
    if datos.sistemas_amortizacion:
        if tipo != "Credito":
            raise problema(
                422,
                "CAMPO_NO_APLICA",
                "Los sistemas de amortización solo aplican a créditos.",
            )
        activos = {
            str(c)
            for c in conn.execute(
                text(
                    "SELECT Codigo FROM Catalogo.SistemaAmortizacion WHERE Estado = 'A'"
                )
            ).scalars()
        }
        if set(datos.sistemas_amortizacion) - activos:
            raise problema(
                422,
                "SISTEMA_NO_EXISTE",
                "Hay sistemas de amortización que no existen o están inactivos.",
            )


def _se_solapan(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Rangos de monto y de vigencia que se cruzan (sin límite = abierto)."""
    tope = date.max
    fechas = a["desde"] <= (b["hasta"] or tope) and b["desde"] <= (a["hasta"] or tope)
    infinito = Decimal("Infinity")
    montos = (a["minimo"] or 0) <= (b["maximo"] or infinito) and (b["minimo"] or 0) <= (
        a["maximo"] or infinito
    )
    return fechas and montos


def _filas(conn: Connection, sql: str, ids: list[int]) -> list[dict[str, Any]]:
    if not ids:
        return []
    lista = "[" + ",".join(str(int(i)) for i in ids) + "]"
    return [dict(r) for r in conn.execute(text(sql), {"ids": lista}).mappings()]


def _producto_de(conn: Connection, destino: Destino, id_: int) -> dict[str, Any]:
    if destino == "producto":
        producto = repo.obtener_producto(conn, id_)
        if producto is None:
            raise problema(404, "PRODUCTO_NO_ENCONTRADO", "El producto no existe.")
        return producto
    sub = repo.obtener_subproducto(conn, id_)
    if sub is None:
        raise problema(404, "SUBPRODUCTO_NO_ENCONTRADO", "El subproducto no existe.")
    producto = repo.obtener_producto(conn, sub["id_producto"])
    if producto is None:
        raise problema(404, "PRODUCTO_NO_ENCONTRADO", "El producto no existe.")
    return producto


def obtener(conn: Connection, destino: Destino, id_: int) -> VinculosVista:
    producto = _producto_de(conn, destino, id_)
    vista = leer(conn, destino, id_)
    if destino == "subproducto":
        # Lo que el subproducto hereda del producto, para mostrarlo en el checklist
        vista["del_producto"] = leer(conn, "producto", producto["id_producto"])
    return VinculosVista.model_validate(vista)


def guardar(
    conn: Connection,
    destino: Destino,
    id_: int,
    datos: VinculosEntrada,
    usuario: Usuario,
    ip: str,
) -> VinculosVista:
    actor = exigir_id_interno(usuario.interno())
    producto = _producto_de(conn, destino, id_)
    antes = _por_tabla_leido(leer(conn, destino, id_))
    despues = _por_tabla_entrada(datos)
    tablas = [clave for clave in _TABLAS if antes[clave] != despues[clave]]
    if not tablas:
        return obtener(conn, destino, id_)
    # Un registro de auditoría por cada tabla de vínculo que cambia (éxito o fallo)
    with ExitStack() as registros:
        for clave in tablas:
            registros.enter_context(
                auditar(
                    "ACTUALIZAR",
                    _TABLA_AUDITORIA[clave],
                    usuario,
                    ip,
                    _detalle(destino, id_, antes[clave], despues[clave]),
                    str(id_),
                )
            )
        try:
            _validar(conn, producto, destino, datos)
            _guardar(conn, destino, id_, datos, actor, tablas)
            conn.commit()
        except DBAPIError as exc:
            conn.rollback()
            raise traducir_error_bd(exc) from None
        except Exception:
            conn.rollback()
            raise
    return obtener(conn, destino, id_)
