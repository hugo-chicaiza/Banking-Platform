/* Ejecutar y guardar resultados antes de 001/002 en SSMS. No cambia la BD. */
SELECT @@SERVERNAME AS Servidor,DB_NAME() AS Base,SYSUTCDATETIME() AS FechaUTC;
SELECT c.name,TYPE_NAME(c.user_type_id) AS Tipo,c.max_length,c.precision,c.scale,
 c.is_nullable,c.is_computed,cc.definition AS ExpresionCalculada,dc.definition AS Defecto
FROM sys.columns c
LEFT JOIN sys.computed_columns cc ON cc.object_id=c.object_id AND cc.column_id=c.column_id
LEFT JOIN sys.default_constraints dc ON dc.object_id=c.default_object_id
WHERE c.object_id=OBJECT_ID('Contabilidad.CuentasContables') ORDER BY c.column_id;
SELECT name,definition,is_disabled,is_not_trusted FROM sys.check_constraints
WHERE parent_object_id=OBJECT_ID('Contabilidad.CuentasContables');
SELECT s.name AS Esquema,o.name,o.type_desc,m.definition
FROM sys.sql_modules m JOIN sys.objects o ON o.object_id=m.object_id
JOIN sys.schemas s ON s.schema_id=o.schema_id
WHERE o.name IN ('trg_CuentasContables_PadreNoImputable','trg_MovimientosContables_CuentaImputable',
 'usp_ContabilizarAsiento') OR m.definition LIKE '%UPDATE%Saldo%';
SELECT c.CodigoCuenta,c.Saldo AS SaldoGuardado,c.EsImputable,c.Naturaleza,c.IdCuentaSuperior,
 COALESCE(SUM(CASE WHEN a.Estado IN ('CONTABILIZADO','REVERSADO')
 THEN CASE WHEN (c.Naturaleza='DEUDORA' AND m.TipoMovimiento='DEBITO')
 OR (c.Naturaleza='ACREEDORA' AND m.TipoMovimiento='CREDITO') THEN m.Monto ELSE -m.Monto END ELSE 0 END),0) AS SaldoPropio
FROM Contabilidad.CuentasContables c
LEFT JOIN Contabilidad.MovimientosContables m ON m.IdCuentaContable=c.IdCuentaContable
LEFT JOIN Contabilidad.AsientoContable a ON a.IdAsientoContable=m.IdAsientoContable
WHERE c.CodigoCuenta IN ('110105','210135','1402','1404','1690','2504','2590','2990','5104','5490','110110','110310','3103')
GROUP BY c.CodigoCuenta,c.Saldo,c.EsImputable,c.Naturaleza,c.IdCuentaSuperior ORDER BY c.CodigoCuenta;
/* Una referencia en una plantilla vigente es un destino potencial, no historico. */
IF OBJECT_ID('Contabilidad.PlantillaAsiento') IS NOT NULL
EXEC(N'SELECT p.CodigoPlantilla,p.Estado,d.Orden,c.CodigoCuenta,c.EsImputable
 FROM Contabilidad.PlantillaAsiento p
 JOIN Contabilidad.PlantillaAsientoDetalle d ON d.IdPlantillaAsiento=p.IdPlantillaAsiento
 JOIN Contabilidad.CuentasContables c ON c.IdCuentaContable=d.IdCuentaContable
 WHERE p.Estado=1 AND LEN(c.CodigoCuenta)<>8 ORDER BY p.CodigoPlantilla,d.Orden');
