/* E4-01. Instalar después del esquema AC-01 y del plan E2-01. */
SET XACT_ABORT ON;
BEGIN TRY
    BEGIN TRANSACTION;
    IF COL_LENGTH('Contabilidad.PlantillaAsiento','Version') IS NULL
    BEGIN
        ALTER TABLE Contabilidad.PlantillaAsiento ADD
            Version smallint NOT NULL CONSTRAINT DF_E401_Version DEFAULT (1),
            VigenciaDesde date NOT NULL CONSTRAINT DF_E401_Desde DEFAULT ('19000101'),
            VigenciaHasta date NULL,
            CreadoPor int NULL,
            AprobadoPor int NULL,
            FechaAprobacion datetime2 NULL,
            CONSTRAINT CK_E401_Vigencia CHECK (VigenciaHasta IS NULL OR VigenciaHasta >= VigenciaDesde),
            CONSTRAINT CK_E401_Aprobador CHECK (AprobadoPor IS NULL OR (CreadoPor IS NOT NULL AND AprobadoPor <> CreadoPor));

        DECLARE @Anterior sysname;
        SELECT @Anterior = k.name
        FROM sys.key_constraints k
        JOIN sys.index_columns i ON i.object_id=k.parent_object_id AND i.index_id=k.unique_index_id
        WHERE k.parent_object_id=OBJECT_ID('Contabilidad.PlantillaAsiento') AND k.type='UQ'
          AND i.key_ordinal=1 AND COL_NAME(i.object_id,i.column_id)='CodigoPlantilla'
          AND NOT EXISTS (SELECT 1 FROM sys.index_columns x
                          WHERE x.object_id=i.object_id AND x.index_id=i.index_id AND x.key_ordinal>1);
        IF @Anterior IS NOT NULL
        BEGIN
            DECLARE @DDL nvarchar(400) = 'ALTER TABLE Contabilidad.PlantillaAsiento DROP CONSTRAINT ' + QUOTENAME(@Anterior);
            EXEC sys.sp_executesql @DDL;
        END;
        EXEC ('CREATE UNIQUE INDEX UX_E401_PlantillaVersion ON Contabilidad.PlantillaAsiento (CodigoPlantilla,Version)');
    END;
    IF COL_LENGTH('Contabilidad.PlantillaAsientoDetalle','OrigenCuenta') IS NULL
    BEGIN
        ALTER TABLE Contabilidad.PlantillaAsientoDetalle ALTER COLUMN IdCuentaContable int NULL;
        ALTER TABLE Contabilidad.PlantillaAsientoDetalle ADD
            OrigenCuenta varchar(15) NOT NULL CONSTRAINT DF_E401_Origen DEFAULT ('FIJA'),
            CodigoRol varchar(30) NULL;
        EXEC ('ALTER TABLE Contabilidad.PlantillaAsientoDetalle ADD CONSTRAINT CK_E401_OrigenCuenta CHECK (
            (OrigenCuenta=''FIJA'' AND IdCuentaContable IS NOT NULL AND CodigoRol IS NULL)
            OR (OrigenCuenta IN (''PRODUCTO'',''CONTRAPRODUCTO'') AND IdCuentaContable IS NULL AND CodigoRol IS NOT NULL)
            OR (OrigenCuenta=''COMISION'' AND IdCuentaContable IS NULL AND CodigoRol IS NULL)
        )');
    END;
    IF COL_LENGTH('Contabilidad.AsientoContable','IdTransaccion') IS NULL
        ALTER TABLE Contabilidad.AsientoContable ADD IdTransaccion bigint NULL;
    IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID('Contabilidad.AsientoContable')
                   AND name='UX_E401_TransaccionTipo')
        EXEC ('CREATE UNIQUE INDEX UX_E401_TransaccionTipo ON Contabilidad.AsientoContable (IdTransaccion,IdTipoAsiento)
               WHERE IdTransaccion IS NOT NULL');
    COMMIT;
END TRY
BEGIN CATCH
    IF XACT_STATE() <> 0 ROLLBACK;
    THROW;
END CATCH;
GO
CREATE OR ALTER TRIGGER Contabilidad.trg_E401_DetalleInmutable
ON Contabilidad.PlantillaAsientoDetalle AFTER INSERT, UPDATE, DELETE AS
BEGIN
    SET NOCOUNT ON;
    IF EXISTS (
        SELECT 1 FROM Contabilidad.AsientoContable a WITH (UPDLOCK,HOLDLOCK)
        JOIN (SELECT IdPlantillaAsiento FROM inserted UNION SELECT IdPlantillaAsiento FROM deleted) d
          ON d.IdPlantillaAsiento=a.IdPlantillaAsiento
    )
        THROW 56103, N'Una plantilla usada requiere una nueva versión.', 1;
END;
GO
CREATE OR ALTER TRIGGER Contabilidad.trg_E401_PlantillaInmutable
ON Contabilidad.PlantillaAsiento AFTER UPDATE, DELETE AS
BEGIN
    SET NOCOUNT ON;
    IF EXISTS (
        SELECT 1 FROM deleted d
        LEFT JOIN inserted i ON i.IdPlantillaAsiento=d.IdPlantillaAsiento
        WHERE EXISTS (SELECT 1 FROM Contabilidad.AsientoContable a WITH (UPDLOCK,HOLDLOCK)
                      WHERE a.IdPlantillaAsiento=d.IdPlantillaAsiento)
          AND (i.IdPlantillaAsiento IS NULL OR EXISTS (
              SELECT d.CodigoPlantilla,d.Version,d.IdTipoAsiento,d.IdConceptoContable,d.Origen,d.Nombre,d.VigenciaDesde,d.Estado,d.CreadoPor,d.AprobadoPor,d.FechaAprobacion
              EXCEPT
              SELECT i.CodigoPlantilla,i.Version,i.IdTipoAsiento,i.IdConceptoContable,i.Origen,i.Nombre,i.VigenciaDesde,i.Estado,i.CreadoPor,i.AprobadoPor,i.FechaAprobacion
          ))
    )
        THROW 56103, N'Una plantilla usada requiere una nueva versión.', 1;
END;

GO
CREATE OR ALTER PROCEDURE Contabilidad.usp_E401_AplicarSaldos @IdAsiento int AS
BEGIN
    SET NOCOUNT ON;
    IF @@TRANCOUNT=0 THROW 56105, N'Se requiere la transacción de origen.', 1;
    DECLARE @Deltas TABLE (IdCuenta int PRIMARY KEY, Monto decimal(18,2));
    ;WITH delta AS (
        SELECT c.IdCuentaContable,c.IdCuentaSuperior,
               CONVERT(decimal(18,2),CASE WHEN c.Naturaleza='DEUDORA' AND m.TipoMovimiento='DEBITO'
                    OR c.Naturaleza='ACREEDORA' AND m.TipoMovimiento='CREDITO'
                    THEN m.Monto ELSE -m.Monto END) AS Monto
        FROM Contabilidad.MovimientosContables m
        JOIN Contabilidad.CuentasContables c ON c.IdCuentaContable=m.IdCuentaContable
        WHERE m.IdAsientoContable=@IdAsiento
        UNION ALL
        SELECT c.IdCuentaContable,c.IdCuentaSuperior,d.Monto
        FROM delta d JOIN Contabilidad.CuentasContables c ON c.IdCuentaContable=d.IdCuentaSuperior
    )
    INSERT @Deltas SELECT IdCuentaContable,SUM(Monto) FROM delta GROUP BY IdCuentaContable;
    DECLARE @Cuenta int, @Monto decimal(18,2);
    DECLARE cuentas CURSOR LOCAL FAST_FORWARD FOR SELECT IdCuenta,Monto FROM @Deltas ORDER BY IdCuenta;
    OPEN cuentas;
    FETCH NEXT FROM cuentas INTO @Cuenta,@Monto;
    WHILE @@FETCH_STATUS=0
    BEGIN
        UPDATE Contabilidad.CuentasContables SET Saldo=Saldo+@Monto,FechaModificacion=SYSDATETIME()
        WHERE IdCuentaContable=@Cuenta;
        FETCH NEXT FROM cuentas INTO @Cuenta,@Monto;
    END;
    CLOSE cuentas;
    DEALLOCATE cuentas;
END;