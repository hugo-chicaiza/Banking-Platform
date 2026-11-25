SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128),SESSION_CONTEXT(N'migration_database')),N'')<>DB_NAME()
    THROW 57650,'Falta confirmar la base destino de E6-05.',1;
BEGIN TRANSACTION;
UPDATE Seguridad.TransaccionesInterfaz SET RolesEjecucion=N'["ADMIN","SUPERVISOR","CUMPLIMIENTO"]'
WHERE CodigoTransaccion IN ('CTA-RETENCION','CTA-LIBERACION') AND BaseObjetivo='cooperativa'
  AND RolesEjecucion=N'["ADMIN","SUPERVISOR"]' AND PermisoAprobacion='cta-retencion'
  AND EsSensible=1 AND Estado='A';
INSERT Seguridad.TransaccionesInterfaz
    (CodigoTransaccion,NombreTransaccion,Modulo,BaseObjetivo,RolesEjecucion,PermisoAprobacion,EsSensible,Estado)
SELECT v.Codigo,v.Nombre,'Cuentas','cooperativa',N'["ADMIN","SUPERVISOR","CUMPLIMIENTO"]','cta-retencion',1,'A'
FROM (VALUES ('CTA-RETENCION',N'Retener saldo'),('CTA-LIBERACION',N'Liberar saldo retenido')) v(Codigo,Nombre)
WHERE NOT EXISTS (SELECT 1 FROM Seguridad.TransaccionesInterfaz WITH(UPDLOCK,HOLDLOCK) WHERE CodigoTransaccion=v.Codigo);
IF EXISTS (
    SELECT 1 FROM Seguridad.TransaccionesInterfaz
    WHERE CodigoTransaccion IN ('CTA-RETENCION','CTA-LIBERACION')
      AND (BaseObjetivo<>'cooperativa' OR RolesEjecucion<>N'["ADMIN","SUPERVISOR","CUMPLIMIENTO"]'
           OR PermisoAprobacion<>'cta-retencion' OR EsSensible<>1 OR Estado<>'A')
)
    THROW 57650, 'La configuración existente de retenciones es incompatible.', 1;
INSERT Auditoria.TipoEvento (CodigoEvento,Modulo,Severidad,EnTransaccion)
SELECT v.Codigo,v.Modulo,v.Severidad,v.EnTransaccion
FROM (VALUES ('CTA_RETENCION', 'cuentas', 'Sensible', 1), ('CTA_LIBERACION', 'cuentas', 'Sensible', 1))
    v(Codigo,Modulo,Severidad,EnTransaccion)
WHERE NOT EXISTS (SELECT 1 FROM Auditoria.TipoEvento WITH(UPDLOCK,HOLDLOCK) WHERE CodigoEvento=v.Codigo);
INSERT Sistema.Tarea (Codigo,Descripcion,Modulo,Programacion,PermiteManual,VentanaEsperadaMin)
SELECT v.Codigo,v.Descripcion,v.Modulo,v.Programacion,v.PermiteManual,v.VentanaEsperadaMin
FROM (VALUES ('CTA_LIBERAR_RETENCIONES',N'Libera retenciones vencidas y verifica saldo retenido','Cuentas','Diaria tras el corte',1,1440))
    v(Codigo,Descripcion,Modulo,Programacion,PermiteManual,VentanaEsperadaMin)
WHERE NOT EXISTS (SELECT 1 FROM Sistema.Tarea WITH(UPDLOCK,HOLDLOCK) WHERE Codigo=v.Codigo);
COMMIT;
