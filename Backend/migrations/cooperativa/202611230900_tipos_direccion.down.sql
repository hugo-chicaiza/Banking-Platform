/* Solo laboratorio/reversión coordinada. Se niega a perder tipos ya usados. */
SET XACT_ABORT ON;
BEGIN TRY
    BEGIN TRANSACTION;
    IF EXISTS (SELECT 1 FROM Clientes.Direcciones
               WHERE TipoDireccion NOT IN ('Domicilio','Trabajo','Correspondencia','Otra'))
        THROW 51057, 'Hay tipos nuevos en uso; no es seguro volver al contrato fijo.', 1;
    IF EXISTS (SELECT 1 FROM sys.foreign_keys
               WHERE name='FK_Direcciones_TipoDireccion'
                 AND parent_object_id=OBJECT_ID('Clientes.Direcciones'))
        ALTER TABLE Clientes.Direcciones DROP CONSTRAINT FK_Direcciones_TipoDireccion;
    IF NOT EXISTS (SELECT 1 FROM sys.check_constraints
                   WHERE name='CK_Direcciones_TipoDireccion_E510')
        ALTER TABLE Clientes.Direcciones ADD CONSTRAINT CK_Direcciones_TipoDireccion_E510
            CHECK (TipoDireccion IN ('Domicilio','Trabajo','Correspondencia','Otra'));
    DROP TABLE IF EXISTS Catalogo.TipoDireccion;
    COMMIT;
END TRY
BEGIN CATCH
    IF XACT_STATE()<>0 ROLLBACK;
    THROW;
END CATCH;
