-- Semilla idempotente E0-09. No actualiza valores ni constantes de otros modulos.
SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128),SESSION_CONTEXT(N'migration_database')),N'')<>DB_NAME()
 THROW 57190,'Falta confirmar la base destino.',1;
BEGIN TRANSACTION;
BEGIN TRY
 INSERT Parametros.Parametro(Clave,Modulo,Descripcion,TipoDato,Unidad,ValorMinimo,ValorMaximo,EsSensible)
 SELECT s.* FROM (VALUES
  ('SES_INACTIVIDAD_MIN','Seguridad',N'Minutos de inactividad de la sesion','Entero','min',5,60,1),
  ('SES_DURACION_MAX_H','Seguridad',N'Horas de vida maxima de la sesion','Entero','h',1,12,1),
  ('APR_DIAS_RESALTAR','Aprobaciones',N'Dias para resaltar una solicitud pendiente','Entero','dias',1,30,0)
 )s(Clave,Modulo,Descripcion,TipoDato,Unidad,Minimo,Maximo,Sensible)
 WHERE NOT EXISTS(SELECT 1 FROM Parametros.Parametro p WITH(UPDLOCK,HOLDLOCK) WHERE p.Clave=s.Clave);
 INSERT Parametros.ParametroValor(IdParametro,Valor,VigenciaDesde,CreadoPor)
 SELECT p.IdParametro,s.Valor,'20260101',NULL
 FROM (VALUES ('SES_INACTIVIDAD_MIN','15'),('SES_DURACION_MAX_H','8'),('APR_DIAS_RESALTAR','3'))s(Clave,Valor)
 JOIN Parametros.Parametro p ON p.Clave=s.Clave
 WHERE NOT EXISTS(SELECT 1 FROM Parametros.ParametroValor v WITH(UPDLOCK,HOLDLOCK) WHERE v.IdParametro=p.IdParametro);
 -- Las banderas no habilitan rutas pendientes ni cambian consumidores ajenos.
 INSERT Parametros.Parametro(Clave,Modulo,Descripcion,TipoDato,EsSensible)
 SELECT s.Clave,s.Modulo,s.Descripcion,'Booleano',0 FROM (VALUES
  ('FUNCION_PARAMETRO_APROBACION','Parametros',N'Aprobacion de cambios de valor de comisiones'),
  ('FUNCION_ATM_RETIRO','ATM',N'Retiros ATM pendientes de habilitacion'),
  ('FUNCION_ATM_REVERSO','ATM',N'Reversos ATM pendientes de habilitacion'),
  ('FUNCION_ATM_TRANSFERENCIA','ATM',N'Transferencias ATM pendientes de habilitacion')
 )s(Clave,Modulo,Descripcion)
 WHERE NOT EXISTS(SELECT 1 FROM Parametros.Parametro p WITH(UPDLOCK,HOLDLOCK) WHERE p.Clave=s.Clave);
 INSERT Parametros.ParametroValor(IdParametro,Valor,VigenciaDesde,CreadoPor)
 SELECT IdParametro,'false','20260101',NULL
 FROM Parametros.Parametro p WHERE Clave IN('FUNCION_PARAMETRO_APROBACION','FUNCION_ATM_RETIRO','FUNCION_ATM_REVERSO','FUNCION_ATM_TRANSFERENCIA')
 AND NOT EXISTS(SELECT 1 FROM Parametros.ParametroValor v WITH(UPDLOCK,HOLDLOCK) WHERE v.IdParametro=p.IdParametro);
 COMMIT TRANSACTION;
END TRY
BEGIN CATCH
 IF @@TRANCOUNT>0 ROLLBACK TRANSACTION;
 THROW;
END CATCH;
