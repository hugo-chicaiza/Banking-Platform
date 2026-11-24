SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57506, 'Falta confirmar la base destino de E5-06.', 1;

BEGIN TRANSACTION;
IF COL_LENGTH('Clientes.RiesgoCliente','IdSolicitud') IS NOT NULL
BEGIN
    EXEC sys.sp_executesql N'IF EXISTS(SELECT 1 FROM Clientes.RiesgoCliente WITH (TABLOCKX,HOLDLOCK)
      WHERE IdSolicitud IS NOT NULL OR
            (VigenteHasta IS NOT NULL AND VigenteHasta <> DATEADD(month, CASE NivelRiesgoLAFT
             WHEN ''Alto'' THEN 12 WHEN ''Medio'' THEN 24 WHEN ''Bajo'' THEN 36 END,CONVERT(date,FechaEvaluacion))))
      THROW 57506, ''Hay decisiones de riesgo con evidencia que debe conservarse.'', 1;';
    ALTER TABLE Clientes.RiesgoCliente DROP COLUMN IdSolicitud, VigenteHasta;
END
DELETE v
FROM Parametros.ParametroValor AS v
JOIN Parametros.Parametro AS p ON p.IdParametro=v.IdParametro
JOIN (VALUES ('CLI_EXIGE_ARCHIVOS','false'),('CLI_RIESGO_VIGENCIA_ALTO_MESES','12'),
             ('CLI_RIESGO_VIGENCIA_MEDIO_MESES','24'),('CLI_RIESGO_VIGENCIA_BAJO_MESES','36')) AS s(Clave,Valor)
    ON p.Clave=s.Clave AND v.Valor=s.Valor
WHERE v.CreadoPor IS NULL AND v.VigenciaDesde='20260101';
DELETE p FROM Parametros.Parametro AS p
WHERE p.Clave IN ('CLI_EXIGE_ARCHIVOS','CLI_RIESGO_VIGENCIA_ALTO_MESES','CLI_RIESGO_VIGENCIA_MEDIO_MESES','CLI_RIESGO_VIGENCIA_BAJO_MESES')
  AND NOT EXISTS(SELECT 1 FROM Parametros.ParametroValor AS v WHERE v.IdParametro=p.IdParametro);
COMMIT TRANSACTION;
