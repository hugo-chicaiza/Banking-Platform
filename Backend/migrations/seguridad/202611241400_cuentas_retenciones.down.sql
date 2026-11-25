SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128),SESSION_CONTEXT(N'migration_database')),N'')<>DB_NAME()
    THROW 57650,'Falta confirmar la base destino de E6-05.',1;
BEGIN TRANSACTION;
DELETE FROM Seguridad.TransaccionesInterfaz WHERE CodigoTransaccion IN ('CTA-RETENCION','CTA-LIBERACION')
  AND NOT EXISTS (SELECT 1 FROM Seguridad.SolicitudAprobacion s WHERE s.CodigoTransaccion=TransaccionesInterfaz.CodigoTransaccion);
DELETE FROM Auditoria.TipoEvento WHERE CodigoEvento IN ('CTA_RETENCION','CTA_LIBERACION')
  AND NOT EXISTS (SELECT 1 FROM Auditoria.Auditoria a WHERE a.CodigoEvento=TipoEvento.CodigoEvento);
DELETE FROM Sistema.Tarea WHERE Codigo='CTA_LIBERAR_RETENCIONES'
  AND NOT EXISTS (SELECT 1 FROM Sistema.TareaEjecucion WHERE Codigo='CTA_LIBERAR_RETENCIONES');
COMMIT;
