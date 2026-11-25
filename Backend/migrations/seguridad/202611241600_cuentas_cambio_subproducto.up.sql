SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57660, 'Falta confirmar la base destino de E6-06.', 1;
BEGIN TRANSACTION;
IF EXISTS (SELECT 1 FROM Seguridad.TransaccionesInterfaz WITH (UPDLOCK,HOLDLOCK)
    WHERE CodigoTransaccion='CTA-SUBPRODUCTO'
      AND (BaseObjetivo<>'cooperativa' OR RolesEjecucion<>N'["ASESOR"]'
           OR PermisoAprobacion<>'cuentas:aprobar' OR EsSensible<>1 OR Estado<>'A'))
    THROW 57660, 'La operacion CTA-SUBPRODUCTO existente es incompatible.', 1;
IF NOT EXISTS (SELECT 1 FROM Seguridad.TransaccionesInterfaz WITH (UPDLOCK,HOLDLOCK)
               WHERE CodigoTransaccion='CTA-SUBPRODUCTO')
BEGIN
    INSERT Seguridad.TransaccionesInterfaz
        (CodigoTransaccion,NombreTransaccion,Modulo,BaseObjetivo,RolesEjecucion,PermisoAprobacion,EsSensible,Estado)
    VALUES ('CTA-SUBPRODUCTO',N'Cambiar subproducto de cuenta','Cuentas','cooperativa',N'["ASESOR"]','cuentas:aprobar',1,'A');
    EXEC sys.sp_addextendedproperty @name=N'E606_OperacionCambioSubproducto', @value=1;
END;
INSERT Auditoria.TipoEvento (CodigoEvento,Modulo,Severidad,EnTransaccion)
SELECT e.Codigo,e.Modulo,e.Severidad,e.EnTransaccion
FROM (VALUES ('CTA_CAMBIO_SUBPRODUCTO', 'cuentas', 'Sensible', 1)) e(Codigo,Modulo,Severidad,EnTransaccion)
WHERE NOT EXISTS (SELECT 1 FROM Auditoria.TipoEvento WITH (UPDLOCK,HOLDLOCK) WHERE CodigoEvento=e.Codigo);
IF @@ROWCOUNT = 1
    EXEC sys.sp_addextendedproperty @name=N'E606_EventoCambioSubproducto', @value=1;
COMMIT TRANSACTION;
