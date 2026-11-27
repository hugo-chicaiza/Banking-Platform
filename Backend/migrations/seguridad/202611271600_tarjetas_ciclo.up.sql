SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57730, 'Confirme la base destino de E6-11.', 1;

BEGIN TRANSACTION;
INSERT Sistema.Tarea (Codigo,Descripcion,Modulo,Programacion,PermiteManual,VentanaEsperadaMin)
SELECT opciones.Codigo,opciones.Descripcion,'Tarjetas',N'Diaria después de medianoche en Ecuador',1,1440
FROM (VALUES ('TAR_VENCER',N'Marca las tarjetas de débito expiradas'),
             ('TAR_ANULAR_NO_RETIRADAS',N'Anula tarjetas generadas sin retiro ni despacho')) opciones(Codigo,Descripcion)
WHERE NOT EXISTS (SELECT 1 FROM Sistema.Tarea t WITH (UPDLOCK,HOLDLOCK) WHERE t.Codigo=opciones.Codigo);

UPDATE Sistema.Tarea SET Estado='A' WHERE Codigo IN ('TAR_VENCER','TAR_ANULAR_NO_RETIRADAS') AND Estado='I';
COMMIT TRANSACTION;
