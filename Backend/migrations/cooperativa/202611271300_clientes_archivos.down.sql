/* Conservar evidencia: solo revertible mientras no existan archivos. */
SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57508, 'Falta confirmar la base destino de E5-08.', 1;

BEGIN TRANSACTION;
IF EXISTS (SELECT 1 FROM Clientes.ClienteArchivo WITH (TABLOCKX,HOLDLOCK))
    THROW 57508, 'Hay respaldos registrados; no se puede retirar el esquema.', 1;

DROP TABLE Clientes.ClienteArchivo;
DROP TABLE Catalogo.ClaseDocumentoCliente;
DELETE v FROM Parametros.ParametroValor v
JOIN Parametros.Parametro p ON p.IdParametro=v.IdParametro
WHERE p.Clave='CLI_ARCHIVO_MAX_BYTES' AND v.CreadoPor IS NULL
    AND v.Valor='5242880' AND v.VigenciaDesde='20260101';
DELETE p FROM Parametros.Parametro p WHERE p.Clave='CLI_ARCHIVO_MAX_BYTES'
AND NOT EXISTS (SELECT 1 FROM Parametros.ParametroValor v WHERE v.IdParametro=p.IdParametro);
COMMIT TRANSACTION;
