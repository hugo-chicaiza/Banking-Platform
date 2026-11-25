/* E6-03: evidencia de solicitud y tipo de documento en el historial existente. */
SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57613, 'Falta confirmar la base destino de E6-03.', 1;

BEGIN TRANSACTION;
IF COL_LENGTH('Canal.CuposModHis', 'SolicitadoPorCliente') IS NULL
    ALTER TABLE Canal.CuposModHis ADD SolicitadoPorCliente bit NULL;
IF COL_LENGTH('Canal.CuposModHis', 'DocumentoVerificado') IS NULL
    ALTER TABLE Canal.CuposModHis ADD DocumentoVerificado varchar(1) NULL;
IF OBJECT_ID('Canal.CK_CuposModHis_PedidoCliente', 'C') IS NULL
    EXEC sys.sp_executesql N'ALTER TABLE Canal.CuposModHis WITH CHECK ADD CONSTRAINT CK_CuposModHis_PedidoCliente
        CHECK ((SolicitadoPorCliente IS NULL AND DocumentoVerificado IS NULL)
            OR (SolicitadoPorCliente IS NOT NULL AND SolicitadoPorCliente = 1
                AND DocumentoVerificado IS NOT NULL AND DocumentoVerificado IN (''C'',''R'',''P'')))';
COMMIT TRANSACTION;
