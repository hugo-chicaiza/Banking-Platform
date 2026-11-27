-- CooperativaDB Dev. Solo lectura antes de ejecutar la migración.
SELECT DB_NAME() AS Base, fecha.Fecha AS FechaContableEfectiva
FROM (VALUES (
    CAST(SYSDATETIMEOFFSET() AT TIME ZONE 'SA Pacific Standard Time' AS datetime2)
)) reloj(HoraEcuador)
LEFT JOIN Contabilidad.FechaContable fecha
  ON fecha.IdFechaContable = Contabilidad.fn_IdFechaContable(reloj.HoraEcuador);

SELECT c.IdCuentaContable, c.CodigoCuenta, c.NombreCuenta,
       padre.CodigoCuenta AS Padre, c.Naturaleza, c.Estado, c.EsImputable,
       c.SoloAutomatica, c.EsCatalogoRegulador, c.EsCuentaValuacion, c.Saldo,
       (SELECT COUNT_BIG(*) FROM Contabilidad.CuentasContables h
        WHERE h.IdCuentaSuperior = c.IdCuentaContable) AS Hijas,
       (SELECT COUNT_BIG(*) FROM Contabilidad.MovimientosContables m
        WHERE m.IdCuentaContable = c.IdCuentaContable) AS Movimientos
FROM Contabilidad.CuentasContables c
LEFT JOIN Contabilidad.CuentasContables padre ON padre.IdCuentaContable = c.IdCuentaSuperior
WHERE c.CodigoCuenta IN ('1990', '199025', '19902505', '19902515', '11010515', '299005')
ORDER BY c.CodigoCuenta;

SELECT cc.name, cc.definition, cc.is_disabled
FROM sys.check_constraints cc
WHERE cc.parent_object_id = OBJECT_ID('Contabilidad.CuentasContables');

SELECT IdTipoAsiento, Codigo, Estado, EsManual
FROM Contabilidad.TiposAsiento WHERE Codigo = 'ATM_FALTANTE';
SELECT IdConceptoContable, CodigoConcepto, Estado
FROM Contabilidad.ConceptoContable WHERE CodigoConcepto = 'AJUSTE_FALTANTE';
SELECT IdPlantillaAsiento, CodigoPlantilla, Version, Estado, VigenciaDesde
FROM Contabilidad.PlantillaAsiento WHERE CodigoPlantilla = 'ATM_FALTANTE';

SELECT m.IdAsientoContable, m.TipoMovimiento, m.Monto, p.CodigoPlantilla, t.Codigo AS Tipo
FROM Contabilidad.CuentasContables c
JOIN Contabilidad.MovimientosContables m ON m.IdCuentaContable = c.IdCuentaContable
LEFT JOIN Contabilidad.AsientoContable a ON a.IdAsientoContable = m.IdAsientoContable
LEFT JOIN Contabilidad.PlantillaAsiento p ON p.IdPlantillaAsiento = a.IdPlantillaAsiento
LEFT JOIN Contabilidad.TiposAsiento t ON t.IdTipoAsiento = a.IdTipoAsiento
WHERE c.CodigoCuenta = '19902515'
ORDER BY m.IdAsientoContable, m.IdMovimientoContable;
