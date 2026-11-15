"""Vínculos uno a varios de productos y subproductos con tasas, comisiones, seguros y
sistemas de amortización (migración 20261117_tasas_y_vinculos).

Un vínculo del producto aplica a todos sus subproductos; uno del subproducto lo
personaliza. Una comisión vinculada al subproducto con exonerado=1 indica que ese
subproducto no la cobra aunque el producto sí. Por ahora solo se guarda el checklist:
el cobro y la elección de tasa los aplicará cada módulo después.

Desmarcar no borra: la fila queda en Estado 'I' (historial) y marcar de nuevo la reactiva.
El SQL de cada tabla es fijo.
"""

from dataclasses import dataclass
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
            SELECT IdTasaInteres AS objeto FROM ProductosFinancieros.ProductoTasaInteres
            WHERE Estado = 'A'
              AND ISNULL(IdProducto, 0) = ISNULL(:id_producto, 0)
              AND ISNULL(IdSubProducto, 0) = ISNULL(:id_sub, 0)
            ORDER BY IdTasaInteres
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
            SELECT IdComision AS objeto, Exonerado AS marca
            FROM ProductosFinancieros.ProductoComision
            WHERE Estado = 'A'
              AND ISNULL(IdProducto, 0) = ISNULL(:id_producto, 0)
              AND ISNULL(IdSubProducto, 0) = ISNULL(:id_sub, 0)
            ORDER BY IdComision
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
            SELECT IdSeguro AS objeto, EsObligatorio AS marca
            FROM ProductosFinancieros.ProductoSeguro
            WHERE Estado = 'A'
              AND ISNULL(IdProducto, 0) = ISNULL(:id_producto, 0)
              AND ISNULL(IdSubProducto, 0) = ISNULL(:id_sub, 0)
            ORDER BY IdSeguro
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
            SELECT CodigoSistema AS objeto
            FROM ProductosFinancieros.ProductoSistemaAmortizacion
            WHERE Estado = 'A'
              AND ISNULL(IdProducto, 0) = ISNULL(:id_producto, 0)
              AND ISNULL(IdSubProducto, 0) = ISNULL(:id_sub, 0)
            ORDER BY CodigoSistema
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


def _guardar(
    conn: Connection, destino: Destino, id_: int, datos: VinculosEntrada, usuario: int
) -> None:
    ids = _ids(destino, id_)
    listas: dict[str, list[tuple[Any, Any]]] = {
        "tasas": [(t, None) for t in datos.tasas_interes],
        "comisiones": [(c.id_comision, c.exonerado) for c in datos.comisiones],
        "seguros": [(s.id_seguro, s.es_obligatorio) for s in datos.seguros],
        "sistemas": [(s, None) for s in datos.sistemas_amortizacion],
    }
    for clave, tabla in _TABLAS.items():
        conn.execute(text(tabla.desactivar), ids)
        for objeto, marca in listas[clave]:
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
        SELECT IdTasaInteres AS id, TipoTasa AS tipo, IdTipoCredito AS tipo_credito
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
    with auditar(
        "ACTUALIZAR",
        "ProductosFinancieros.ProductoTasaInteres",
        usuario,
        ip,
        f"PRD-VINCULOS {destino} tasas={len(datos.tasas_interes)}"
        f" comisiones={len(datos.comisiones)} seguros={len(datos.seguros)}"
        f" sistemas={len(datos.sistemas_amortizacion)}",
        str(id_),
    ):
        try:
            producto = _producto_de(conn, destino, id_)
            _validar(conn, producto, destino, datos)
            _guardar(conn, destino, id_, datos, actor)
            conn.commit()
        except DBAPIError as exc:
            conn.rollback()
            raise traducir_error_bd(exc) from None
        except Exception:
            conn.rollback()
            raise
    return obtener(conn, destino, id_)
