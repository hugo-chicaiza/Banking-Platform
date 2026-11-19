CREATE OR ALTER VIEW Contabilidad.vw_ConciliacionEfectivo
AS
/* El mayor incluye el saldo propio histórico de 110105 y los tres auxiliares
   del corte E201. El asiento de reclasificación compensa entre esas cuentas. */
SELECT
    c.Contable,
    f.Bovedas,
    f.CajasAbiertas,
    f.Gavetas,
    f.Bovedas + f.CajasAbiertas + f.Gavetas AS Fisico,
    c.Contable - (f.Bovedas + f.CajasAbiertas + f.Gavetas) AS Diferencia
FROM (
    SELECT ISNULL(SUM(CASE WHEN m.TipoMovimiento = 'DEBITO' THEN m.Monto
                           ELSE -m.Monto END), 0) AS Contable
    FROM Contabilidad.MovimientosContables AS m
    JOIN Contabilidad.AsientoContable AS a
        ON a.IdAsientoContable = m.IdAsientoContable
       AND a.Estado IN ('CONTABILIZADO', 'REVERSADO')
    JOIN Contabilidad.CuentasContables AS cc
        ON cc.IdCuentaContable = m.IdCuentaContable
       AND cc.CodigoCuenta IN ('110105', '11010505', '11010510', '11010515')
) AS c
CROSS JOIN (
    SELECT
        (
            SELECT ISNULL(SUM(SaldoActual), 0)
            FROM Boveda.Boveda
        ) AS Bovedas,
        (
            SELECT ISNULL(SUM(x.Saldo), 0)
            FROM (
                SELECT j.DineroInicial
                       + ISNULL(dt.Monto, 0)
                       + ISNULL(mv.Monto, 0)
                       - ISNULL(dv.Monto, 0) AS Saldo
                FROM Caja.JornadasCaja AS j
                OUTER APPLY (
                    SELECT SUM(d.Monto) AS Monto
                    FROM Caja.DotacionesCaja AS d
                    WHERE d.IdJornadaCaja = j.IdJornadaCaja
                      AND d.Estado <> 'ANULADA'
                      AND d.TipoDotacion = 'ADICIONAL'
                ) AS dt
                OUTER APPLY (
                    SELECT SUM(CASE WHEN t.Naturaleza = 'I' THEN m.Monto
                                    ELSE -m.Monto END) AS Monto
                    FROM Caja.MovimientosCaja AS m
                    JOIN Caja.TipoMovimientoCaja AS t
                        ON t.IdTipoMovimientoCaja = m.IdTipoMovimiento
                    WHERE m.IdJornadaCaja = j.IdJornadaCaja
                ) AS mv
                OUTER APPLY (
                    SELECT SUM(v.Monto) AS Monto
                    FROM Caja.DevolucionesCaja AS v
                    WHERE v.IdJornadaCaja = j.IdJornadaCaja
                      AND v.Estado <> 'ANULADA'
                ) AS dv
                WHERE j.Estado = 'ABIERTA'
            ) AS x
        ) AS CajasAbiertas,
        (
            SELECT ISNULL(SUM(g.CantidadActual * d.Valor), 0)
            FROM ATM.Gaveta AS g
            JOIN Catalogo.Denominacion AS d
                ON d.IdDenominacion = g.IdDenominacion
        ) AS Gavetas
) AS f;
