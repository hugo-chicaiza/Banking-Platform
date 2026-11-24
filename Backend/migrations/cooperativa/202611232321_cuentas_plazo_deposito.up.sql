SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57611, 'Falta confirmar la base destino de E6-01.', 1;
BEGIN TRANSACTION;
IF NOT EXISTS(SELECT 1 FROM Parametros.Parametro WITH (UPDLOCK,HOLDLOCK) WHERE Clave='CTA_DIAS_SIN_DEPOSITO')
    INSERT Parametros.Parametro(Clave,Modulo,Descripcion,TipoDato,Unidad,ValorMinimo,EsSensible)
    VALUES ('CTA_DIAS_SIN_DEPOSITO','Cuentas',N'Plazo para el primer depósito','Entero','dias',1,0);
INSERT Parametros.ParametroValor(IdParametro,Valor,VigenciaDesde,CreadoPor)
SELECT p.IdParametro,'30','20260101',NULL FROM Parametros.Parametro AS p
WHERE p.Clave='CTA_DIAS_SIN_DEPOSITO'
  AND NOT EXISTS(SELECT 1 FROM Parametros.ParametroValor AS v WITH (UPDLOCK,HOLDLOCK) WHERE v.IdParametro=p.IdParametro);
COMMIT TRANSACTION;
