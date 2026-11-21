-- E3-06 · reversa (solo fuera de producción). Los cupos sembrados se identifican por su fecha.
SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128),SESSION_CONTEXT(N'migration_database')),N'')<>DB_NAME()
 THROW 57810,'Confirme la base destino de E3-06.',1;
BEGIN TRY
 BEGIN TRANSACTION;
 UPDATE ProductosFinancieros.SubProducto SET EstadoSubProducto = 'Suspendido', Estado = 'I' WHERE CodigoSubProducto = 'AHO001-MN';
 UPDATE ProductosFinancieros.SubProducto SET EstadoSubProducto = 'Activo', Estado = 'A' WHERE CodigoSubProducto IN ('AHO003-PER', 'AHO002-FAM');
 DELETE c FROM ProductosFinancieros.ProductoCanalCupo c JOIN ProductosFinancieros.SubProducto s ON s.IdSubProducto = c.IdSubProducto
 WHERE c.VigenciaDesde = '20261120' AND c.IdSolicitud IS NULL AND s.CodigoSubProducto <> 'AHO001-PN';
 DELETE r FROM ProductosFinancieros.ProductoRestriccion r JOIN ProductosFinancieros.SubProducto s ON s.IdSubProducto = r.IdSubProducto
 WHERE s.CodigoSubProducto = 'APO001-STD' AND r.TipoRestriccion IN ('SIN_RETIROS', 'SIN_TRANSFERENCIAS_SALIDA') AND r.IdSolicitud IS NULL;
 UPDATE ProductosFinancieros.SubProducto SET MaximoPorCliente = NULL WHERE CodigoSubProducto = 'APO001-STD';
 COMMIT TRANSACTION;
END TRY
BEGIN CATCH
 IF @@TRANCOUNT>0 ROLLBACK TRANSACTION;
 THROW;
END CATCH;
