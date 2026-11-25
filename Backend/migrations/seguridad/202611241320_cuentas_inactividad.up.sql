SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57640, 'Falta confirmar la base destino de E6-04.', 1;

BEGIN TRANSACTION;
IF EXISTS (
    SELECT 1 FROM Seguridad.TransaccionesInterfaz WITH (UPDLOCK, HOLDLOCK)
    WHERE CodigoTransaccion='CTA-ESTADO'
      AND (BaseObjetivo<>'cooperativa' OR RolesEjecucion<>N'["SUPERVISOR"]'
           OR PermisoAprobacion<>'cuentas:aprobar' OR EsSensible<>1)
)
    THROW 57640, 'La operación CTA-ESTADO existente es incompatible.', 1;

INSERT Seguridad.TransaccionesInterfaz
    (CodigoTransaccion, NombreTransaccion, Modulo, BaseObjetivo, RolesEjecucion, PermisoAprobacion, EsSensible, Estado)
SELECT 'CTA-ESTADO', N'Desbloquear cuenta', 'Cuentas', 'cooperativa', N'["SUPERVISOR"]', 'cuentas:aprobar', 1, 'A'
WHERE NOT EXISTS (SELECT 1 FROM Seguridad.TransaccionesInterfaz WITH (UPDLOCK, HOLDLOCK) WHERE CodigoTransaccion='CTA-ESTADO');
UPDATE Seguridad.TransaccionesInterfaz SET Estado='A' WHERE CodigoTransaccion='CTA-ESTADO' AND Estado='I';

INSERT Auditoria.TipoEvento (CodigoEvento, Modulo, Severidad, EnTransaccion)
SELECT v.CodigoEvento, v.Modulo, v.Severidad, v.EnTransaccion
FROM (VALUES ('CTA_DESBLOQUEO', 'cuentas', 'Sensible', 1),
             ('CTA_BLOQUEO', 'cuentas', 'Sensible', 0),
             ('CTA_REACTIVACION', 'cuentas', 'Sensible', 0),
             ('CTA_INACTIVACION', 'cuentas', 'Sensible', 0)) v(CodigoEvento,Modulo,Severidad,EnTransaccion)
WHERE NOT EXISTS (SELECT 1 FROM Auditoria.TipoEvento WITH (UPDLOCK, HOLDLOCK) WHERE CodigoEvento=v.CodigoEvento);

INSERT Sistema.Tarea (Codigo, Descripcion, Modulo, Programacion, PermiteManual, VentanaEsperadaMin)
SELECT v.Codigo,v.Descripcion,v.Modulo,v.Programacion,v.PermiteManual,v.VentanaEsperadaMin
FROM (VALUES ('CTA_INACTIVIDAD', N'Inactiva cuentas sin movimientos iniciados por el cliente',
       'Cuentas', N'Diaria tras el corte', 1, 1440)) v(Codigo,Descripcion,Modulo,Programacion,PermiteManual,VentanaEsperadaMin)
WHERE NOT EXISTS (
    SELECT 1 FROM Sistema.Tarea WITH (UPDLOCK, HOLDLOCK) WHERE Codigo=v.Codigo
);
COMMIT TRANSACTION;
