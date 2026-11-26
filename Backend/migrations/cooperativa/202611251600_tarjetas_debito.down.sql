SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57710, 'Confirme la base destino de E6-10.', 1;

BEGIN TRANSACTION;

IF COL_LENGTH('Tarjeta.EnviosTarjeta', 'DespachadoEn') IS NOT NULL
    EXEC(N'IF EXISTS (SELECT 1 FROM Tarjeta.EnviosTarjeta WHERE DespachadoEn IS NOT NULL)
        THROW 57711, ''Hay despachos registrados; preserve los datos antes de revertir.'', 1;');
IF COL_LENGTH('Tarjeta.Tarjeta', 'EntregaVerificadaEn') IS NOT NULL
    EXEC(N'IF EXISTS (SELECT 1 FROM Tarjeta.Tarjeta WHERE EntregaVerificadaEn IS NOT NULL
        OR SobreDescargadoEn IS NOT NULL OR MotivoEstado IS NOT NULL OR IdTarjetaReemplazada IS NOT NULL
        OR RequiereEntregaVerificada = 1)
        THROW 57711, ''Hay operaciones E6-10; preserve los datos antes de revertir.'', 1;');

ALTER TABLE Tarjeta.EnviosTarjeta DROP COLUMN IF EXISTS CodigoSeguimiento, DespachadoEn;
ALTER TABLE Tarjeta.Tarjeta DROP CONSTRAINT IF EXISTS FK_Tarjeta_Reemplazada, FK_Tarjeta_MotivoEstado;
ALTER TABLE Tarjeta.Tarjeta DROP CONSTRAINT IF EXISTS DF_Tarjeta_EntregaVerificada;
ALTER TABLE Tarjeta.Tarjeta DROP COLUMN IF EXISTS IdTarjetaReemplazada, MotivoEstado,
    EntregaVerificadaEn, SobreDescargadoEn, RequiereEntregaVerificada;
DROP TABLE IF EXISTS Catalogo.MotivoEstadoTarjeta;

COMMIT;
