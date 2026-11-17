"""SQL de E1-12; todos los valores del cliente se envían como parámetros."""

from datetime import date, datetime
from typing import Any

from sqlalchemy import Connection, text

Fila = dict[str, Any]
_COMISION = """
    SELECT IdComision AS id_comision, CodigoComision AS codigo_comision,
        TipoComision AS tipo_comision, TipoCalculo AS tipo_calculo, Valor AS valor,
        MontoMinimo AS monto_minimo, MontoMaximo AS monto_maximo, IdCanal AS id_canal,
        Descripcion AS descripcion, VigenciaDesde AS vigencia_desde,
        VigenciaHasta AS vigencia_hasta, Estado AS estado,
        IdCuentaContableIngreso AS id_cuenta_contable_ingreso
    FROM Transacciones.Comisiones
"""
_EXONERACION = """
    SELECT IdExoneracion AS id_exoneracion, IdComision AS id_comision,
        IdProducto AS id_producto, IdSubProducto AS id_sub_producto,
        TipoCliente AS tipo_cliente, OperacionesGratisMes AS operaciones_gratis_mes,
        PorcentajeExonerado AS porcentaje_exonerado, VigenciaDesde AS vigencia_desde,
        VigenciaHasta AS vigencia_hasta, Estado AS estado, CreadoPor AS creado_por,
        FechaCreacion AS fecha_creacion
    FROM Transacciones.ExoneracionComision
"""


def _filas(conn: Connection, sql: str, datos: Fila | None = None) -> list[Fila]:
    return [dict(f) for f in conn.execute(text(sql), datos or {}).mappings()]


def _fila(conn: Connection, sql: str, datos: Fila) -> Fila | None:
    filas = _filas(conn, sql, datos)
    return filas[0] if filas else None


def bloquear_comisiones(conn: Connection) -> None:
    conn.execute(
        text(
            "SELECT COUNT_BIG(*) FROM Transacciones.Comisiones WITH (TABLOCKX,HOLDLOCK)"
        )
    )


def listar_comisiones(conn: Connection) -> list[Fila]:
    return _filas(conn, _COMISION + " ORDER BY IdComision")


def obtener_comision(conn: Connection, id_: int) -> Fila | None:
    return _fila(conn, _COMISION + " WHERE IdComision=:id", {"id": id_})


def asociaciones(conn: Connection, id_: int) -> list[Fila]:
    return _filas(
        conn,
        """
        SELECT IdComisionTipoTransaccion AS id_comision_tipo_transaccion,
            CodigoTipoTransaccion AS codigo_tipo_transaccion, VigenciaDesde AS vigencia_desde,
            VigenciaHasta AS vigencia_hasta, Estado AS estado, RegistradoPor AS registrado_por
        FROM Transacciones.ComisionTipoTransaccion WHERE IdComision=:id
        ORDER BY VigenciaDesde,IdComisionTipoTransaccion
    """,
        {"id": id_},
    )


def canal_activo(conn: Connection, id_: int) -> bool:
    return (
        conn.execute(
            text("SELECT 1 FROM Canal.Canal WHERE IdCanal=:id AND Estado='A'"),
            {"id": id_},
        ).first()
        is not None
    )


def tipo_activo(conn: Connection, codigo: str) -> bool:
    return (
        conn.execute(
            text(
                "SELECT 1 FROM Transacciones.TipoTransaccion WHERE CodigoTipo=:codigo AND Estado='A'"
            ),
            {"codigo": codigo},
        ).first()
        is not None
    )


def codigo_existe(conn: Connection, codigo: str) -> bool:
    return (
        conn.execute(
            text("SELECT 1 FROM Transacciones.Comisiones WHERE CodigoComision=:codigo"),
            {"codigo": codigo},
        ).first()
        is not None
    )


def insertar_comision(conn: Connection, datos: Fila) -> int:
    return int(
        conn.execute(
            text("""
        INSERT Transacciones.Comisiones (CodigoComision,TipoComision,TipoCalculo,Valor,
            MontoMinimo,MontoMaximo,IdCanal,Descripcion,VigenciaDesde,VigenciaHasta,IdCuentaContableIngreso)
        OUTPUT inserted.IdComision
        VALUES (:codigo_comision,:tipo_comision,:tipo_calculo,:valor,:monto_minimo,:monto_maximo,
            :id_canal,:descripcion,:vigencia_desde,:vigencia_hasta,:id_cuenta_contable_ingreso)
    """),
            datos,
        ).scalar_one()
    )


def asociaciones_solapadas(conn: Connection, datos: Fila) -> list[Fila]:
    return _filas(
        conn,
        """
        SELECT IdComision AS id_comision, VigenciaDesde AS vigencia_desde, VigenciaHasta AS vigencia_hasta
        FROM Transacciones.ComisionTipoTransaccion WITH (TABLOCKX,HOLDLOCK)
        WHERE CodigoTipoTransaccion=:codigo_tipo_transaccion AND IdCanal=:id_canal AND Estado='A'
          AND (:vigencia_hasta IS NULL OR VigenciaDesde<:vigencia_hasta)
          AND (VigenciaHasta IS NULL OR VigenciaHasta>:vigencia_desde)
    """,
        datos,
    )


def insertar_asociacion(conn: Connection, datos: Fila, actor: int) -> None:
    conn.execute(
        text("""
        INSERT Transacciones.ComisionTipoTransaccion
            (CodigoTipoTransaccion,IdCanal,IdComision,VigenciaDesde,VigenciaHasta,RegistradoPor)
        VALUES (:codigo_tipo_transaccion,:id_canal,:id_comision,:vigencia_desde,:vigencia_hasta,:actor)
    """),
        {**datos, "actor": actor},
    )


def listar_exoneraciones(
    conn: Connection, id_comision: int | None = None
) -> list[Fila]:
    return _filas(
        conn,
        _EXONERACION + " WHERE (:id IS NULL OR IdComision=:id) ORDER BY IdExoneracion",
        {"id": id_comision},
    )


def obtener_exoneracion(conn: Connection, id_: int) -> Fila | None:
    return _fila(
        conn,
        _EXONERACION + " WITH (UPDLOCK,HOLDLOCK) WHERE IdExoneracion=:id",
        {"id": id_},
    )


def bloquear_exoneraciones(conn: Connection) -> None:
    conn.execute(
        text(
            "SELECT COUNT_BIG(*) FROM Transacciones.ExoneracionComision WITH (TABLOCKX,HOLDLOCK)"
        )
    )


def producto_existe(conn: Connection, id_: int) -> bool:
    return (
        conn.execute(
            text("SELECT 1 FROM ProductosFinancieros.Producto WHERE IdProducto=:id"),
            {"id": id_},
        ).first()
        is not None
    )


def producto_de_subproducto(conn: Connection, id_: int) -> int | None:
    return conn.execute(
        text(
            "SELECT IdProducto FROM ProductosFinancieros.SubProducto WHERE IdSubProducto=:id"
        ),
        {"id": id_},
    ).scalar_one_or_none()


def insertar_exoneracion(conn: Connection, datos: Fila, actor: int) -> int:
    return int(
        conn.execute(
            text("""
        INSERT Transacciones.ExoneracionComision (IdComision,IdProducto,IdSubProducto,TipoCliente,
            OperacionesGratisMes,PorcentajeExonerado,VigenciaDesde,VigenciaHasta,Estado,CreadoPor)
        OUTPUT inserted.IdExoneracion
        VALUES (:id_comision,:id_producto,:id_sub_producto,:tipo_cliente,:operaciones_gratis_mes,
            :porcentaje_exonerado,:vigencia_desde,:vigencia_hasta,:estado,:actor)
    """),
            {**datos, "actor": actor},
        ).scalar_one()
    )


_COLUMNAS_COMISION = {
    "descripcion": "Descripcion",
    "estado": "Estado",
    "id_cuenta_contable_ingreso": "IdCuentaContableIngreso",
}
_COLUMNAS_EXONERACION = {
    "id_producto": "IdProducto",
    "id_sub_producto": "IdSubProducto",
    "tipo_cliente": "TipoCliente",
    "operaciones_gratis_mes": "OperacionesGratisMes",
    "porcentaje_exonerado": "PorcentajeExonerado",
    "vigencia_desde": "VigenciaDesde",
    "vigencia_hasta": "VigenciaHasta",
    "estado": "Estado",
}


def actualizar_comision(conn: Connection, id_: int, cambios: Fila) -> None:
    datos: Fila = {"id": id_}
    for campo in _COLUMNAS_COMISION:
        datos[campo] = cambios.get(campo)
        datos["c_" + campo] = int(campo in cambios)
    conn.execute(
        text("""
        UPDATE Transacciones.Comisiones SET
            Descripcion=CASE WHEN :c_descripcion=1 THEN :descripcion ELSE Descripcion END,
            Estado=CASE WHEN :c_estado=1 THEN :estado ELSE Estado END,
            IdCuentaContableIngreso=CASE WHEN :c_id_cuenta_contable_ingreso=1
                THEN :id_cuenta_contable_ingreso ELSE IdCuentaContableIngreso END
        WHERE IdComision=:id
    """),
        datos,
    )


def actualizar_exoneracion(conn: Connection, id_: int, cambios: Fila) -> None:
    datos: Fila = {"id": id_}
    for campo in _COLUMNAS_EXONERACION:
        datos[campo] = cambios.get(campo)
        datos["c_" + campo] = int(campo in cambios)
    conn.execute(
        text("""
        UPDATE Transacciones.ExoneracionComision SET
            IdProducto=CASE WHEN :c_id_producto=1 THEN :id_producto ELSE IdProducto END,
            IdSubProducto=CASE WHEN :c_id_sub_producto=1 THEN :id_sub_producto ELSE IdSubProducto END,
            TipoCliente=CASE WHEN :c_tipo_cliente=1 THEN :tipo_cliente ELSE TipoCliente END,
            OperacionesGratisMes=CASE WHEN :c_operaciones_gratis_mes=1 THEN :operaciones_gratis_mes ELSE OperacionesGratisMes END,
            PorcentajeExonerado=CASE WHEN :c_porcentaje_exonerado=1 THEN :porcentaje_exonerado ELSE PorcentajeExonerado END,
            VigenciaDesde=CASE WHEN :c_vigencia_desde=1 THEN :vigencia_desde ELSE VigenciaDesde END,
            VigenciaHasta=CASE WHEN :c_vigencia_hasta=1 THEN :vigencia_hasta ELSE VigenciaHasta END,
            Estado=CASE WHEN :c_estado=1 THEN :estado ELSE Estado END
        WHERE IdExoneracion=:id
    """),
        datos,
    )


def contexto_cuenta(conn: Connection, id_: int) -> Fila | None:
    return _fila(
        conn,
        """
        SELECT c.IdSubProducto AS id_sub_producto,s.IdProducto AS id_producto,cl.TipoCliente AS tipo_cliente
        FROM Cuentas.Cuenta c WITH (UPDLOCK,HOLDLOCK)
        JOIN ProductosFinancieros.SubProducto s ON s.IdSubProducto=c.IdSubProducto
        JOIN Clientes.Cliente cl ON cl.IdCliente=c.IdCliente WHERE c.IdCuenta=:id
    """,
        {"id": id_},
    )


def tarifas_vigentes(
    conn: Connection, tipo: str, canal: int, fecha: date
) -> list[Fila]:
    return _filas(
        conn,
        """
        SELECT c.IdComision AS id_comision,c.TipoCalculo AS tipo_calculo,
            c.Valor AS valor,c.MontoMinimo AS monto_minimo,c.MontoMaximo AS monto_maximo
        FROM Transacciones.Comisiones c
        WHERE c.Estado='A' AND c.IdCanal=:canal AND c.VigenciaDesde<=:fecha
          AND (c.VigenciaHasta IS NULL OR c.VigenciaHasta>:fecha)
          AND EXISTS (SELECT 1 FROM Transacciones.ComisionTipoTransaccion a
            WHERE a.IdComision=c.IdComision AND a.IdCanal=:canal AND a.CodigoTipoTransaccion=:tipo
              AND a.Estado='A' AND a.VigenciaDesde<=:fecha AND (a.VigenciaHasta IS NULL OR a.VigenciaHasta>:fecha))
    """,
        {"tipo": tipo, "canal": canal, "fecha": fecha},
    )


def operaciones_previas(
    conn: Connection, cuenta: int, tipo: str, canal: int, fecha: datetime
) -> int:
    return int(
        conn.execute(
            text("""
        SELECT COUNT_BIG(*) FROM Transacciones.Transaccion
        WHERE IdCuenta=:cuenta AND TipoTransaccion=:tipo AND IdCanal=:canal
          AND TipoOperacion='Normal' AND Estado='Completada'
          AND FechaHoraSistema>=:inicio AND FechaHoraSistema<:fecha
    """),
            {
                "cuenta": cuenta,
                "tipo": tipo,
                "canal": canal,
                "inicio": fecha.replace(
                    day=1, hour=0, minute=0, second=0, microsecond=0
                ),
                "fecha": fecha,
            },
        ).scalar_one()
    )
