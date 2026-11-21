-- E0-09: referencia inicial a la hora de corte real, sin modificar el calendario.
-- Los consumidores contables siguen usando su funcion y calendario existentes.
SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128),SESSION_CONTEXT(N'migration_database')),N'')<>DB_NAME()
 THROW 57190,'Falta confirmar la base destino.',1;
IF OBJECT_ID(N'Contabilidad.FechaContable',N'U') IS NOT NULL
BEGIN
 DECLARE @fecha date=CONVERT(date,SWITCHOFFSET(SYSDATETIMEOFFSET(),'-05:00'));
 DECLARE @hora time(7);
 SELECT @hora=HoraCorte FROM Contabilidad.FechaContable WHERE Fecha=@fecha;
 -- No inventar una hora si la linea base no tiene el calendario del dia.
 IF @hora IS NOT NULL
 BEGIN
  IF DATEPART(second,@hora)<>0 OR DATEPART(nanosecond,@hora)<>0
   THROW 57190,'La hora del calendario tiene precision no compatible con HH:MM; revisar sin modificarla.',1;
  BEGIN TRANSACTION;
  BEGIN TRY
   IF NOT EXISTS(SELECT 1 FROM Parametros.Parametro WITH(UPDLOCK,HOLDLOCK) WHERE Clave='CON_HORA_CORTE')
    INSERT Parametros.Parametro(Clave,Modulo,Descripcion,TipoDato,Unidad,EsSensible,Estado)
    VALUES('CON_HORA_CORTE','Contabilidad',N'Referencia del calendario; pendiente de integrar su consumidor','Hora','hora',1,'I');
   INSERT Parametros.ParametroValor(IdParametro,Valor,VigenciaDesde,CreadoPor)
   SELECT IdParametro,CONVERT(char(5),@hora,108),@fecha,NULL FROM Parametros.Parametro p
   WHERE Clave='CON_HORA_CORTE' AND TipoDato='Hora'
   AND NOT EXISTS(SELECT 1 FROM Parametros.ParametroValor v WITH(UPDLOCK,HOLDLOCK) WHERE v.IdParametro=p.IdParametro);
   COMMIT TRANSACTION;
  END TRY
  BEGIN CATCH
   IF @@TRANCOUNT>0 ROLLBACK TRANSACTION;
   THROW;
  END CATCH;
 END;
END;
