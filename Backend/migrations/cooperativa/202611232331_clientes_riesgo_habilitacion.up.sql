/* E5-06: vigencias históricas según nivel y bandera de archivos E5-08. */
SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57506, 'Falta confirmar la base destino de E5-06.', 1;

BEGIN TRANSACTION;
IF COL_LENGTH('Clientes.RiesgoCliente','VigenteHasta') IS NULL
    ALTER TABLE Clientes.RiesgoCliente ADD VigenteHasta date NULL;
IF COL_LENGTH('Clientes.RiesgoCliente','IdSolicitud') IS NULL
    ALTER TABLE Clientes.RiesgoCliente ADD IdSolicitud bigint NULL;
EXEC sys.sp_executesql N'
    UPDATE Clientes.RiesgoCliente
    SET VigenteHasta=DATEADD(month, CASE NivelRiesgoLAFT
            WHEN ''Alto'' THEN 12 WHEN ''Medio'' THEN 24 WHEN ''Bajo'' THEN 36 END,
            CONVERT(date,FechaEvaluacion))
    WHERE VigenteHasta IS NULL AND NivelRiesgoLAFT IN (''Alto'',''Medio'',''Bajo'');';

INSERT Parametros.Parametro(Clave,Modulo,Descripcion,TipoDato,Unidad,ValorMinimo,EsSensible)
SELECT semilla.Clave,'Clientes',semilla.Descripcion,semilla.TipoDato,semilla.Unidad,semilla.Minimo,1
FROM (VALUES
    ('CLI_EXIGE_ARCHIVOS',N'Exigir archivos obligatorios para habilitación','Booleano',NULL,NULL),
    ('CLI_RIESGO_VIGENCIA_ALTO_MESES',N'Vigencia de riesgo alto','Entero','meses',1),
    ('CLI_RIESGO_VIGENCIA_MEDIO_MESES',N'Vigencia de riesgo medio','Entero','meses',1),
    ('CLI_RIESGO_VIGENCIA_BAJO_MESES',N'Vigencia de riesgo bajo','Entero','meses',1)
) AS semilla(Clave,Descripcion,TipoDato,Unidad,Minimo)
WHERE NOT EXISTS(SELECT 1 FROM Parametros.Parametro AS p WITH (UPDLOCK,HOLDLOCK) WHERE p.Clave=semilla.Clave);

INSERT Parametros.ParametroValor(IdParametro,Valor,VigenciaDesde,CreadoPor)
SELECT p.IdParametro,s.Valor,'20260101',NULL
FROM (VALUES ('CLI_EXIGE_ARCHIVOS','false'),('CLI_RIESGO_VIGENCIA_ALTO_MESES','12'),
             ('CLI_RIESGO_VIGENCIA_MEDIO_MESES','24'),('CLI_RIESGO_VIGENCIA_BAJO_MESES','36')) AS s(Clave,Valor)
JOIN Parametros.Parametro AS p ON p.Clave=s.Clave
WHERE NOT EXISTS(SELECT 1 FROM Parametros.ParametroValor AS v WITH (UPDLOCK,HOLDLOCK) WHERE v.IdParametro=p.IdParametro);
COMMIT TRANSACTION;
