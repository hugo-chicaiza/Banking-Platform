from datetime import date
from typing import Any

from sqlalchemy import Connection, text

# Las tres consultas son de solo lectura. "Vigente" = la fecha de hoy cae entre
# VigenciaDesde y VigenciaHasta (nula = sin fin); "activo" = Estado 'A'.


def _rows(
    conn: Connection, sql: str, params: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(text(sql), params or {}).mappings()]


# CRE-01 / CRE-02: tasas vigentes del tipo de crédito


def tasas_vigentes(
    conn: Connection,
    id_tipo_credito: int,
    hoy: date,
    id_producto: int | None = None,
    id_sub_producto: int | None = None,
) -> list[dict[str, Any]]:
    """Tasas de crédito activas y vigentes vinculadas: las del subproducto si tiene; si
    no, las de su producto. Una tasa sin vincular no rige para nadie."""
    return _rows(
        conn,
        """
        WITH vinculadas AS (
            SELECT v.IdTasaInteres,
                   CASE WHEN v.IdSubProducto IS NOT NULL THEN 1 ELSE 2 END AS nivel
            FROM ProductosFinancieros.ProductoTasaInteres AS v
            JOIN Credito.TasaInteres AS tv
              ON tv.IdTasaInteres = v.IdTasaInteres
             AND tv.Estado = 'A' AND tv.TipoTasa = 'CREDITO'
            WHERE v.Estado = 'A'
              AND ((:id_sub IS NOT NULL AND v.IdSubProducto = :id_sub)
                   OR v.IdProducto = COALESCE(:id_producto,
                          (SELECT s.IdProducto FROM ProductosFinancieros.SubProducto AS s
                           WHERE s.IdSubProducto = :id_sub)))
        ),
        nivel AS (SELECT MIN(nivel) AS n FROM vinculadas)
        SELECT t.IdTipoCredito AS id_tipo_credito,
               t.TasaNominalAnual AS tasa_nominal_anual,
               t.PlazoMaximoMeses AS plazo_maximo_meses,
               t.RecargoMoraSobreTasa AS recargo_mora_sobre_tasa,
               t.MontoMinimo AS monto_minimo,
               t.MontoMaximo AS monto_maximo
        FROM Credito.TasaInteres AS t
        WHERE t.IdTipoCredito = :id_tipo_credito
          AND t.TipoTasa = 'CREDITO'
          AND t.Estado = 'A'
          AND t.VigenciaDesde <= :hoy
          AND (t.VigenciaHasta IS NULL OR t.VigenciaHasta >= :hoy)
          AND t.IdTasaInteres IN (SELECT IdTasaInteres FROM vinculadas
                                  WHERE nivel = (SELECT n FROM nivel))
        ORDER BY t.IdTasaInteres
        """,
        {
            "id_tipo_credito": id_tipo_credito,
            "hoy": hoy,
            "id_producto": id_producto,
            "id_sub": id_sub_producto,
        },
    )


def seguros_activos(
    conn: Connection, id_tipo_credito: int, hoy: date
) -> list[dict[str, Any]]:
    return _rows(
        conn,
        """
        SELECT s.IdSeguro AS id,
               s.CodigoSeguro AS codigo,
               s.Nombre AS nombre,
               s.TipoCalculo AS tipo_calculo,
               s.Valor AS valor,
               tcs.EsObligatorio AS obligatorio
        FROM Credito.TipoCreditoSeguro tcs
        JOIN Credito.Seguro s ON s.IdSeguro = tcs.IdSeguro
        WHERE tcs.IdTipoCredito = :id_tipo_credito
          AND tcs.Estado = 'A'
          AND s.Estado = 'A'
          AND s.VigenciaDesde <= :hoy
          AND (s.VigenciaHasta IS NULL OR s.VigenciaHasta >= :hoy)
        ORDER BY s.IdSeguro
        """,
        {"id_tipo_credito": id_tipo_credito, "hoy": hoy},
    )


def impuestos_activos(
    conn: Connection, id_tipo_credito: int, hoy: date
) -> list[dict[str, Any]]:
    # TipoCreditoImpuesto no tiene EsObligatorio: un impuesto siempre se cobra
    return _rows(
        conn,
        """
        SELECT i.IdImpuesto AS id,
               i.CodigoImpuesto AS codigo,
               i.Nombre AS nombre,
               i.TipoCalculo AS tipo_calculo,
               i.Valor AS valor,
               CAST(1 AS bit) AS obligatorio
        FROM Credito.TipoCreditoImpuesto tci
        JOIN Credito.Impuesto i ON i.IdImpuesto = tci.IdImpuesto
        WHERE tci.IdTipoCredito = :id_tipo_credito
          AND tci.Estado = 'A'
          AND i.Estado = 'A'
          AND i.VigenciaDesde <= :hoy
          AND (i.VigenciaHasta IS NULL OR i.VigenciaHasta >= :hoy)
        ORDER BY i.IdImpuesto
        """,
        {"id_tipo_credito": id_tipo_credito, "hoy": hoy},
    )
