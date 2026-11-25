SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57611, 'Falta confirmar la base destino de E6-01.', 1;
BEGIN TRANSACTION;
IF NOT EXISTS (SELECT 1 FROM sys.extended_properties WHERE class=0 AND name=N'E601_TareaPrevia')
BEGIN
    DECLARE @previa bit=CASE WHEN EXISTS(
        SELECT 1 FROM Sistema.Tarea WITH (UPDLOCK,HOLDLOCK) WHERE Codigo='CTA_ANULAR_SIN_DEPOSITO'
    ) THEN 1 ELSE 0 END;
    EXEC sys.sp_addextendedproperty @name=N'E601_TareaPrevia', @value=@previa;
END;
IF NOT EXISTS(SELECT 1 FROM Sistema.Tarea WITH (UPDLOCK,HOLDLOCK) WHERE Codigo='CTA_ANULAR_SIN_DEPOSITO')
    INSERT Sistema.Tarea(Codigo,Descripcion,Modulo,Programacion,PermiteManual,VentanaEsperadaMin)
    VALUES ('CTA_ANULAR_SIN_DEPOSITO',N'Anula cuentas vencidas sin primer depósito','Cuentas','diaria',0,1500);
COMMIT TRANSACTION;
