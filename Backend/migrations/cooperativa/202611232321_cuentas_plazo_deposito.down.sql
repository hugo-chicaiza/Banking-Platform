SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57611, 'Falta confirmar la base destino de E6-01.', 1;
BEGIN TRANSACTION;
DELETE v FROM Parametros.ParametroValor AS v JOIN Parametros.Parametro AS p ON p.IdParametro=v.IdParametro
WHERE p.Clave='CTA_DIAS_SIN_DEPOSITO' AND v.Valor='30' AND v.VigenciaDesde='20260101' AND v.CreadoPor IS NULL;
DELETE p FROM Parametros.Parametro AS p WHERE p.Clave='CTA_DIAS_SIN_DEPOSITO'
    AND NOT EXISTS(SELECT 1 FROM Parametros.ParametroValor AS v WHERE v.IdParametro=p.IdParametro);
COMMIT TRANSACTION;
