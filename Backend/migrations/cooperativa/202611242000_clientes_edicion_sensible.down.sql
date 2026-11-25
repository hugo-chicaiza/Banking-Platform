/* E5-04 abajo (solo fuera de producción): borra el historial nuevo de antes/después. */
SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57504, 'Falta confirmar la base destino de E5-04.', 1;

BEGIN TRANSACTION;
DELETE v FROM Parametros.ParametroValor AS v
JOIN Parametros.Parametro AS p ON p.IdParametro = v.IdParametro
WHERE p.Clave = 'CLI_MAX_EMAILS_SECUNDARIOS';
DELETE FROM Parametros.Parametro WHERE Clave = 'CLI_MAX_EMAILS_SECUNDARIOS';

IF COL_LENGTH('Clientes.ClientesHis', 'IdSolicitud') IS NOT NULL
    ALTER TABLE Clientes.ClientesHis DROP COLUMN IdSolicitud, ValorAnterior, ValorNuevo;
IF COL_LENGTH('Clientes.Cliente', 'EmailVerificadoPor') IS NOT NULL
    ALTER TABLE Clientes.Cliente DROP COLUMN EmailVerificadoPor, FechaEmailVerificado;
DROP TABLE IF EXISTS Clientes.ClienteEmail;
COMMIT TRANSACTION;
