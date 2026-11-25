SET NOCOUNT ON;
SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57660, 'Falta confirmar la base destino de E6-06.', 1;
BEGIN TRANSACTION;
IF EXISTS (SELECT 1 FROM sys.extended_properties WHERE class=0 AND name=N'E606_OperacionCambioSubproducto')
BEGIN
    IF EXISTS (SELECT 1 FROM Seguridad.SolicitudAprobacion WITH (UPDLOCK,HOLDLOCK) WHERE CodigoTransaccion='CTA-SUBPRODUCTO')
        THROW 57660, 'Existen solicitudes de cambio. Se conserva el historico.', 1;
    DELETE FROM Seguridad.TransaccionesInterfaz WHERE CodigoTransaccion='CTA-SUBPRODUCTO';
    EXEC sys.sp_dropextendedproperty @name=N'E606_OperacionCambioSubproducto';
END;
IF EXISTS (SELECT 1 FROM sys.extended_properties WHERE class=0 AND name=N'E606_EventoCambioSubproducto')
   AND NOT EXISTS (SELECT 1 FROM Auditoria.Auditoria WHERE CodigoEvento='CTA_CAMBIO_SUBPRODUCTO')
BEGIN
    DELETE FROM Auditoria.TipoEvento WHERE CodigoEvento='CTA_CAMBIO_SUBPRODUCTO';
    EXEC sys.sp_dropextendedproperty @name=N'E606_EventoCambioSubproducto';
END;
COMMIT TRANSACTION;
