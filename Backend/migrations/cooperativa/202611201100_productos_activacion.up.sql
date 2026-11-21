-- E3-01 / E3-06 (2026-11-20): configuración que faltaba y estados de los subproductos que no
-- cumplen la lista de activación. Decisiones del usuario del 2026-11-20.
SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128),SESSION_CONTEXT(N'migration_database')),N'')<>DB_NAME()
 THROW 57810,'Confirme la base destino de E3-06.',1;
BEGIN TRY
 BEGIN TRANSACTION;
 DECLARE @hoy date = CONVERT(date, SYSDATETIMEOFFSET() AT TIME ZONE 'SA Pacific Standard Time');
 DECLARE @registra int = 8;  -- administrador que configuró los vínculos existentes

 /* 1. Certificados de aportación: uno por cliente, sin retiros ni transferencias de salida
       (E3-01). Sin máximos propios del cliente, rige lo que la entidad configura en el subproducto. */
 UPDATE ProductosFinancieros.SubProducto SET MaximoPorCliente = 1 WHERE CodigoSubProducto = 'APO001-STD';
 INSERT ProductosFinancieros.ProductoRestriccion (IdSubProducto,TipoRestriccion,Descripcion,VigenciaDesde,Estado,RegistradoPor)
 SELECT s.IdSubProducto, v.Tipo, v.Descripcion, @hoy, 'A', @registra
 FROM ProductosFinancieros.SubProducto s
 CROSS JOIN (VALUES ('SIN_RETIROS', 'Los aportes no se retiran; se rescatan al salir de la cooperativa.'),
                    ('SIN_TRANSFERENCIAS_SALIDA', 'Los aportes no se transfieren a otras cuentas.')) v(Tipo, Descripcion)
 WHERE s.CodigoSubProducto = 'APO001-STD'
   AND NOT EXISTS (SELECT 1 FROM ProductosFinancieros.ProductoRestriccion r
                   WHERE r.IdSubProducto = s.IdSubProducto AND r.TipoRestriccion = v.Tipo AND r.Estado = 'A');

 /* 2. Cupos semejantes: cada subproducto de ahorro o corriente recibe, en los canales donde no
       tiene cupo vigente, los mismos techos que el ahorro a la vista (AHO001-PN). */
 IF NOT EXISTS (SELECT 1 FROM ProductosFinancieros.ProductoCanalCupo c JOIN ProductosFinancieros.SubProducto s ON s.IdSubProducto = c.IdSubProducto
                WHERE s.CodigoSubProducto = 'AHO001-PN' AND c.EstadoCupo = 'A' AND c.VigenciaHasta IS NULL)
  THROW 57810,'Falta el cupo de referencia de AHO001-PN.',1;
 INSERT ProductosFinancieros.ProductoCanalCupo (IdCanal,CupoDiarioMaximo,CupoMensualMaximo,MontoMaxTransaccion,MaxTransaccionesDia,IdSubProducto,VigenciaDesde,EstadoCupo)
 SELECT ref.IdCanal, ref.CupoDiarioMaximo, ref.CupoMensualMaximo, ref.MontoMaxTransaccion, ref.MaxTransaccionesDia, s.IdSubProducto, @hoy, 'A'
 FROM ProductosFinancieros.SubProducto s
 JOIN ProductosFinancieros.Producto p ON p.IdProducto = s.IdProducto
 JOIN ProductosFinancieros.TipoProducto t ON t.IdTipoProducto = p.IdTipoProducto
 CROSS JOIN (SELECT c.* FROM ProductosFinancieros.ProductoCanalCupo c JOIN ProductosFinancieros.SubProducto r ON r.IdSubProducto = c.IdSubProducto
             WHERE r.CodigoSubProducto = 'AHO001-PN' AND c.EstadoCupo = 'A' AND c.VigenciaHasta IS NULL) ref
 WHERE t.Codigo IN ('CUENTA_AHORRO', 'CUENTA_CORRIENTE') AND ISNULL(s.EstadoSubProducto, '') <> 'Retirado'
   AND NOT EXISTS (SELECT 1 FROM ProductosFinancieros.ProductoCanalCupo x
                   WHERE x.IdSubProducto = s.IdSubProducto AND x.IdCanal = ref.IdCanal AND x.EstadoCupo = 'A'
                     AND (x.VigenciaHasta IS NULL OR x.VigenciaHasta >= @hoy));

 /* 3. Estados (E3-06): menores queda en Borrador hasta que el módulo de clientes verifique al
       tutor; AHO003-PER (producto en Borrador, sin condiciones ni numeración) y AHO002-FAM (sin
       regla de numeración) no cumplen la lista de activación. Ninguno tiene cuentas. */
 IF EXISTS (SELECT 1 FROM Cuentas.Cuenta c JOIN ProductosFinancieros.SubProducto s ON s.IdSubProducto = c.IdSubProducto
            WHERE s.CodigoSubProducto IN ('AHO001-MN', 'AHO003-PER', 'AHO002-FAM'))
  THROW 57810,'Un subproducto a corregir ya tiene cuentas: revisar antes de cambiar su estado.',1;
 UPDATE ProductosFinancieros.SubProducto SET EstadoSubProducto = 'Borrador', Estado = 'I', FechaModificacion = SYSUTCDATETIME()
 WHERE CodigoSubProducto IN ('AHO001-MN', 'AHO003-PER', 'AHO002-FAM');
 COMMIT TRANSACTION;
END TRY
BEGIN CATCH
 IF @@TRANCOUNT>0 ROLLBACK TRANSACTION;
 THROW;
END CATCH;
