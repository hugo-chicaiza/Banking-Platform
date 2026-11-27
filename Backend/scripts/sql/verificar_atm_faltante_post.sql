-- CooperativaDB Dev. Solo lectura después del alta y antes del registro E4-03.
SELECT DB_NAME() AS Base, c.IdCuentaContable, c.CodigoCuenta, c.NombreCuenta,
       padre.CodigoCuenta AS Padre, c.Naturaleza, c.Estado, c.EsImputable,
       c.SoloAutomatica, c.EsCatalogoRegulador, c.EsCuentaValuacion, c.Saldo,
       cuentas.Hijas, movimientos.Total AS Movimientos,
       CASE WHEN c.CodigoCuenta = '19902515' AND padre.CodigoCuenta = '199025'
                 AND c.Naturaleza = 'DEUDORA' AND c.Estado = 1 AND c.EsImputable = 1
                 AND c.SoloAutomatica = 0 AND c.EsCatalogoRegulador = 0
                 AND c.EsCuentaValuacion = 0 AND cuentas.Hijas = 0
                 AND c.Saldo = 0 AND movimientos.Total = 0
            THEN 'LISTO_PARA_GENERAR' ELSE 'REVISAR_AUXILIAR' END AS Resultado
FROM (VALUES ('19902515')) esperado(CodigoCuenta)
LEFT JOIN Contabilidad.CuentasContables c ON c.CodigoCuenta = esperado.CodigoCuenta
LEFT JOIN Contabilidad.CuentasContables padre ON padre.IdCuentaContable = c.IdCuentaSuperior
CROSS APPLY (
    SELECT COUNT_BIG(*) AS Hijas FROM Contabilidad.CuentasContables h
    WHERE h.IdCuentaSuperior = c.IdCuentaContable
) cuentas
CROSS APPLY (
    SELECT COUNT_BIG(*) AS Total FROM Contabilidad.MovimientosContables m
    WHERE m.IdCuentaContable = c.IdCuentaContable
) movimientos;

SELECT IdPlantillaAsiento, CodigoPlantilla, Version, Estado, VigenciaDesde
FROM Contabilidad.PlantillaAsiento WHERE CodigoPlantilla = 'ATM_FALTANTE';
