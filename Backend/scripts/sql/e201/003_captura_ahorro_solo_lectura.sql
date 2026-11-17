/* SSMS, CooperativaDB. SOLO LECTURA sobre tablas de negocio.
   Ejecutar antes de reclasificar, con operaciones detenidas.
   No usa NOLOCK ni compara capturas tomadas a horas diferentes.
   SERIALIZABLE + bloqueos compartidos de tabla: lectura consistente aun sin RCSI.
   Puede bloquear escrituras mientras se captura; no ejecutar en hora operativa.
   Exportar TODOS los resultados juntos, incluida fecha/hora y alcance.
   Referencias previas (no constituyen corte): PN 798 lineas / 86646.76;
   PJ 61 / 76000.00; 859 / 162646.76 total.
*/
SET NOCOUNT ON;
SET XACT_ABORT ON;
SET TRANSACTION ISOLATION LEVEL SERIALIZABLE;
BEGIN TRY
 BEGIN TRANSACTION;
 DECLARE @n bigint;
 SELECT @n=COUNT_BIG(*) FROM Contabilidad.AsientoContable WITH(TABLOCK,HOLDLOCK);
 SELECT @n=COUNT_BIG(*) FROM Contabilidad.MovimientosContables WITH(TABLOCK,HOLDLOCK);
 SELECT @n=COUNT_BIG(*) FROM Contabilidad.CuentasContables WITH(TABLOCK,HOLDLOCK);
 SELECT @n=COUNT_BIG(*) FROM Transacciones.Transaccion WITH(TABLOCK,HOLDLOCK);
 SELECT @n=COUNT_BIG(*) FROM Cuentas.Cuenta WITH(TABLOCK,HOLDLOCK);
 SELECT @n=COUNT_BIG(*) FROM ProductosFinancieros.SubProducto WITH(TABLOCK,HOLDLOCK);
 DECLARE @FechaUTC datetime2=SYSUTCDATETIME(),@IdCorte uniqueidentifier=NEWID();
 SELECT @IdCorte AS IdCorte,@FechaUTC AS FechaCapturaUTC,
 CONVERT(varchar(40),@FechaUTC AT TIME ZONE 'UTC' AT TIME ZONE 'SA Pacific Standard Time') AS FechaCapturaEcuador,
 DB_NAME() AS Base,
 N'Libro: 210135, estados CONTABILIZADO y REVERSADO (incluye original y reverso); desglose por subproducto ACTUAL de la cuenta vinculada por IdTransaccion. Operativo: TODAS las cuentas PN/PJ, todos los estados, saldo total (sin restar retenido). Sin filtro de agencia.' AS Alcance;

 SELECT COALESCE(sp.CodigoSubProducto,'SIN_MAPEO') AS CodigoSubProducto,
 COUNT_BIG(*) AS Lineas,
 SUM(CASE WHEN m.TipoMovimiento='CREDITO' THEN m.Monto ELSE -m.Monto END) AS SaldoAcreedor
 INTO #Libro
 FROM Contabilidad.MovimientosContables m
 JOIN Contabilidad.CuentasContables cc ON cc.IdCuentaContable=m.IdCuentaContable
 JOIN Contabilidad.AsientoContable a ON a.IdAsientoContable=m.IdAsientoContable
 LEFT JOIN Transacciones.Transaccion t ON t.IdTransaccion=m.IdTransaccion
 LEFT JOIN Cuentas.Cuenta c ON c.IdCuenta=t.IdCuenta
 LEFT JOIN ProductosFinancieros.SubProducto sp ON sp.IdSubProducto=c.IdSubProducto
 WHERE cc.CodigoCuenta='210135' AND a.Estado IN ('CONTABILIZADO','REVERSADO')
 GROUP BY COALESCE(sp.CodigoSubProducto,'SIN_MAPEO');
 SELECT sp.CodigoSubProducto,COUNT_BIG(*) AS Cuentas,SUM(c.Saldo) AS SaldoOperativo,
 SUM(c.SaldoRetenido) AS SaldoRetenido
 INTO #Operativo
 FROM Cuentas.Cuenta c JOIN ProductosFinancieros.SubProducto sp ON sp.IdSubProducto=c.IdSubProducto
 WHERE sp.CodigoSubProducto IN ('AHO001-PN','AHO001-PJ') GROUP BY sp.CodigoSubProducto;
 SELECT @IdCorte AS IdCorte,@FechaUTC AS FechaCapturaUTC,v.CodigoSubProducto,
 CASE v.CodigoSubProducto WHEN 'AHO001-PN' THEN '21013505' WHEN 'AHO001-PJ' THEN '21013510' END AS AuxiliarPropuesto,
 COALESCE(l.Lineas,0) AS Lineas,COALESCE(l.SaldoAcreedor,0) AS Libro,
 COALESCE(o.Cuentas,0) AS Cuentas,COALESCE(o.SaldoOperativo,0) AS Operativo,
 COALESCE(l.SaldoAcreedor,0)-COALESCE(o.SaldoOperativo,0) AS Diferencia,
 CASE WHEN v.CodigoSubProducto NOT IN ('AHO001-PN','AHO001-PJ') THEN 'BLOQUEADO: SIN DESTINO'
 WHEN COALESCE(l.SaldoAcreedor,0)<>COALESCE(o.SaldoOperativo,0) THEN 'BLOQUEADO: DIFERENCIA'
 ELSE 'CUADRA: REQUIERE REVISION Y APROBACION' END AS Resultado
 FROM (SELECT CodigoSubProducto FROM #Libro UNION SELECT CodigoSubProducto FROM #Operativo
       UNION SELECT 'AHO001-PN' UNION SELECT 'AHO001-PJ') v
 LEFT JOIN #Libro l ON l.CodigoSubProducto=v.CodigoSubProducto
 LEFT JOIN #Operativo o ON o.CodigoSubProducto=v.CodigoSubProducto
 ORDER BY v.CodigoSubProducto;
 SELECT @IdCorte AS IdCorte,cc.CodigoCuenta,cc.Saldo AS SaldoGuardado,
 (SELECT COALESCE(SUM(SaldoAcreedor),0) FROM #Libro) AS Libro210135,
 (SELECT COALESCE(SUM(SaldoOperativo),0) FROM #Operativo) AS OperativoPNPJ,
 (SELECT COALESCE(SUM(SaldoAcreedor),0) FROM #Libro)-(SELECT COALESCE(SUM(SaldoOperativo),0) FROM #Operativo) AS Diferencia
 FROM Contabilidad.CuentasContables cc WHERE cc.CodigoCuenta='210135';
 /* Detalle del alcance operativo, sin datos personales. Incluye cuentas cerradas
    para detectar saldo residual; no ocultarlo filtrando solo activas. */
 SELECT sp.CodigoSubProducto,c.Estado,COUNT_BIG(*) AS Cuentas,SUM(c.Saldo) AS Saldo,
 SUM(c.SaldoRetenido) AS Retenido FROM Cuentas.Cuenta c
 JOIN ProductosFinancieros.SubProducto sp ON sp.IdSubProducto=c.IdSubProducto
 WHERE sp.CodigoSubProducto IN ('AHO001-PN','AHO001-PJ') GROUP BY sp.CodigoSubProducto,c.Estado;
 COMMIT;
 DROP TABLE #Libro;
 DROP TABLE #Operativo;
 SET TRANSACTION ISOLATION LEVEL READ COMMITTED;
END TRY
BEGIN CATCH
 IF XACT_STATE()<>0 ROLLBACK;
 DROP TABLE IF EXISTS #Libro;
 DROP TABLE IF EXISTS #Operativo;
 SET TRANSACTION ISOLATION LEVEL READ COMMITTED;
 THROW;
END CATCH;
