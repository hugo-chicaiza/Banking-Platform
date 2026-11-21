/* PROPUESTA, no activar en Azure antes de integrar y probar el flujo físico.
   No reutiliza Cobro_Comision. Evento sin principal: solo la comisión mueve saldo.
   Requiere confirmación explícita en SESSION_CONTEXT en esta conexión. */
SET XACT_ABORT ON;
IF COALESCE(TRY_CONVERT(bit, SESSION_CONTEXT(N'e112.aprobar_evento_reposicion')),0) <> 1
    THROW 51104, 'Propuesta pendiente de integrar y aprobar el flujo de reposicion.', 1;
BEGIN TRY
    BEGIN TRANSACTION;
    DECLARE @Filas bigint;
    SELECT @Filas=COUNT_BIG(*) FROM Transacciones.TipoTransaccion WITH (TABLOCKX,HOLDLOCK);
    IF EXISTS (SELECT 1 FROM Transacciones.TipoTransaccion WHERE CodigoTipo='Reposicion_Tarjeta'
        AND (Naturaleza IS NOT NULL OR AfectaSaldo<>0 OR Estado<>'A'))
        THROW 51104, 'Evento de reposicion existente incompatible con la propuesta.', 1;
    IF NOT EXISTS (SELECT 1 FROM Transacciones.TipoTransaccion WHERE CodigoTipo='Reposicion_Tarjeta')
        INSERT Transacciones.TipoTransaccion (CodigoTipo,Nombre,Naturaleza,AfectaSaldo,Descripcion,Estado)
        VALUES ('Reposicion_Tarjeta','Reposicion de tarjeta',NULL,0,'Evento fisico; el cargo se registra solo como comision.','A');
    COMMIT;
END TRY
BEGIN CATCH
    IF XACT_STATE()<>0 ROLLBACK;
    THROW;
END CATCH;
