-- CooperativaDB. Ejecutar antes de cargar las plantillas.
SET XACT_ABORT ON;
BEGIN TRY
    BEGIN TRANSACTION;

    CREATE TABLE Contabilidad.PlantillaAsiento (
        IdPlantillaAsiento int IDENTITY(1,1) NOT NULL PRIMARY KEY,
        CodigoPlantilla varchar(50) NOT NULL UNIQUE,
        IdConceptoContable int NOT NULL REFERENCES Contabilidad.ConceptoContable(IdConceptoContable),
        Origen varchar(30) NOT NULL,
        IdTipoAsiento int NOT NULL REFERENCES Contabilidad.TiposAsiento(IdTipoAsiento),
        Nombre varchar(100) NOT NULL,
        Estado bit NOT NULL DEFAULT (0),
        CONSTRAINT CK_PlantillaAsiento_Origen CHECK (Origen IN (
            'CAJA', 'ATM', 'BOVEDA', 'CUENTAS', 'CREDITO', 'TARJETA',
            'TRANSACCIONES', 'NOMINA', 'MANUAL', 'CIERRE', 'AJUSTE'
        ))
    );

    CREATE TABLE Contabilidad.PlantillaAsientoDetalle (
        IdPlantillaAsientoDetalle int IDENTITY(1,1) NOT NULL PRIMARY KEY,
        IdPlantillaAsiento int NOT NULL REFERENCES Contabilidad.PlantillaAsiento(IdPlantillaAsiento),
        Orden smallint NOT NULL CHECK (Orden > 0),
        IdCuentaContable int NOT NULL REFERENCES Contabilidad.CuentasContables(IdCuentaContable),
        TipoMovimiento varchar(30) NOT NULL CHECK (TipoMovimiento IN ('DEBITO', 'CREDITO')),
        ComponenteImporte varchar(30) NOT NULL CHECK (LEN(ComponenteImporte) > 0),
        CONSTRAINT UQ_PlantillaAsientoDetalle_Orden UNIQUE (IdPlantillaAsiento, Orden)
    );

    ALTER TABLE Contabilidad.AsientoContable ADD
        IdPlantillaAsiento int NULL REFERENCES Contabilidad.PlantillaAsiento(IdPlantillaAsiento),
        ClaveEventoContable varchar(100) NULL,
        HuellaEventoContable char(64) NULL;

    -- Compilar las referencias a las columnas después de agregarlas.
    EXEC sys.sp_executesql N'
        ALTER TABLE Contabilidad.AsientoContable
        ADD CONSTRAINT CK_AsientoContable_IdentidadEvento CHECK (
            (ClaveEventoContable IS NULL AND HuellaEventoContable IS NULL)
            OR (ClaveEventoContable IS NOT NULL AND HuellaEventoContable IS NOT NULL)
        );

        CREATE UNIQUE INDEX UX_AsientoContable_Evento
        ON Contabilidad.AsientoContable (ClaveEventoContable)
        WHERE ClaveEventoContable IS NOT NULL;
    ';

    COMMIT TRANSACTION;
END TRY
BEGIN CATCH
    IF XACT_STATE() <> 0
        ROLLBACK TRANSACTION;
    THROW;
END CATCH;
