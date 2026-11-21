/* E1-12 #104. Ejecutar en la base CooperativaDB seleccionada en SSMS.
   No crea la FK contable: destino pendiente de confirmar.
   No modifica el cobrador ni selecciona reglas de exoneración. */
SET XACT_ABORT ON;
BEGIN TRY
    BEGIN TRANSACTION;
    IF COL_LENGTH('Transacciones.Comisiones', 'IdCuentaContableIngreso') IS NULL
        ALTER TABLE Transacciones.Comisiones ADD IdCuentaContableIngreso int NULL;
    IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('Transacciones.Comisiones')
        AND name='IdCuentaContableIngreso' AND system_type_id=56 AND is_nullable=1)
        THROW 51104, 'IdCuentaContableIngreso existente debe ser int nullable; revisar esquema.', 1;

    IF OBJECT_ID('Transacciones.ExoneracionComision', 'U') IS NULL
    BEGIN
        CREATE TABLE Transacciones.ExoneracionComision (
            IdExoneracion int IDENTITY(1,1) NOT NULL
                CONSTRAINT PK_ExoneracionComision PRIMARY KEY,
            IdComision int NOT NULL,
            IdProducto int NULL,
            IdSubProducto int NULL,
            TipoCliente varchar(10) NULL,
            OperacionesGratisMes smallint NULL,
            PorcentajeExonerado decimal(5,2) NOT NULL
                CONSTRAINT DF_Exoneracion_Porcentaje DEFAULT (100),
            VigenciaDesde date NOT NULL,
            VigenciaHasta date NULL,
            Estado char(1) NOT NULL CONSTRAINT DF_Exoneracion_Estado DEFAULT ('A'),
            IdSolicitud bigint NULL,
            CreadoPor int NULL,
            FechaCreacion datetime2 NOT NULL
                CONSTRAINT DF_Exoneracion_Fecha DEFAULT (SYSUTCDATETIME()),
            CONSTRAINT FK_Exoneracion_Comision FOREIGN KEY (IdComision)
                REFERENCES Transacciones.Comisiones (IdComision),
            CONSTRAINT FK_Exoneracion_Producto FOREIGN KEY (IdProducto)
                REFERENCES ProductosFinancieros.Producto (IdProducto),
            CONSTRAINT FK_Exoneracion_SubProducto FOREIGN KEY (IdSubProducto)
                REFERENCES ProductosFinancieros.SubProducto (IdSubProducto)
        );
    END;

    /* Recrear estos dos CHECK también corrige el borrador que excluía el 0.
       WITH CHECK valida los datos existentes; cualquier fallo revierte todo. */
    IF OBJECT_ID('Transacciones.CK_Exoneracion_Porcentaje', 'C') IS NOT NULL
        ALTER TABLE Transacciones.ExoneracionComision DROP CONSTRAINT CK_Exoneracion_Porcentaje;
    ALTER TABLE Transacciones.ExoneracionComision WITH CHECK ADD
        CONSTRAINT CK_Exoneracion_Porcentaje CHECK (PorcentajeExonerado BETWEEN 0 AND 100);
    IF OBJECT_ID('Transacciones.CK_Exoneracion_CupoMes', 'C') IS NOT NULL
        ALTER TABLE Transacciones.ExoneracionComision DROP CONSTRAINT CK_Exoneracion_CupoMes;
    ALTER TABLE Transacciones.ExoneracionComision WITH CHECK ADD
        CONSTRAINT CK_Exoneracion_CupoMes CHECK (OperacionesGratisMes IS NULL OR OperacionesGratisMes >= 0);

    IF OBJECT_ID('Transacciones.CK_Exoneracion_TipoCliente', 'C') IS NULL
        ALTER TABLE Transacciones.ExoneracionComision WITH CHECK ADD
            CONSTRAINT CK_Exoneracion_TipoCliente CHECK (TipoCliente IS NULL OR TipoCliente IN ('Natural','Juridico'));
    IF OBJECT_ID('Transacciones.CK_Exoneracion_Vigencia', 'C') IS NULL
        ALTER TABLE Transacciones.ExoneracionComision WITH CHECK ADD
            CONSTRAINT CK_Exoneracion_Vigencia CHECK (VigenciaHasta IS NULL OR VigenciaHasta > VigenciaDesde);
    IF OBJECT_ID('Transacciones.CK_Exoneracion_Estado', 'C') IS NULL
        ALTER TABLE Transacciones.ExoneracionComision WITH CHECK ADD
            CONSTRAINT CK_Exoneracion_Estado CHECK (Estado IN ('A','I'));
    ALTER TABLE Transacciones.ExoneracionComision WITH CHECK CHECK CONSTRAINT ALL;
    COMMIT;
END TRY
BEGIN CATCH
    IF XACT_STATE() <> 0 ROLLBACK;
    THROW;
END CATCH;
