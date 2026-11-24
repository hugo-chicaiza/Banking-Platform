/* E6-03: la reversión preserva el historial si ya contiene evidencia. */
SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57613, 'Falta confirmar la base destino de E6-03.', 1;

BEGIN TRANSACTION;
IF COL_LENGTH('Canal.CuposModHis', 'SolicitadoPorCliente') IS NOT NULL
   AND COL_LENGTH('Canal.CuposModHis', 'DocumentoVerificado') IS NOT NULL
BEGIN
    EXEC sys.sp_executesql N'IF EXISTS (SELECT 1 FROM Canal.CuposModHis WITH (TABLOCKX, HOLDLOCK)
         WHERE SolicitadoPorCliente IS NOT NULL OR DocumentoVerificado IS NOT NULL)
         THROW 57613, ''Existen ajustes auditados; se conserva la evidencia.'', 1;';
    ALTER TABLE Canal.CuposModHis DROP CONSTRAINT IF EXISTS CK_CuposModHis_PedidoCliente;
    ALTER TABLE Canal.CuposModHis DROP COLUMN SolicitadoPorCliente, DocumentoVerificado;
END
COMMIT TRANSACTION;
