SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57508, 'Falta confirmar la base destino de E5-08.', 1;

BEGIN TRANSACTION;
INSERT Auditoria.TipoEvento (CodigoEvento,Modulo,Severidad,EnTransaccion)
SELECT v.Codigo,v.Modulo,v.Severidad,v.EnTransaccion
FROM (VALUES ('CLI_ARCHIVO_SUBIDO','clientes','Sensible',0),
             ('CLI_ARCHIVO_VISTO','clientes','Sensible',1),
             ('CLI_ARCHIVO_RECHAZADO','clientes','Sensible',0))
  v(Codigo,Modulo,Severidad,EnTransaccion)
WHERE NOT EXISTS (SELECT 1 FROM Auditoria.TipoEvento WHERE CodigoEvento=v.Codigo);

INSERT Sistema.Tarea(Codigo,Descripcion,Modulo,Programacion,PermiteManual,VentanaEsperadaMin)
SELECT v.Codigo,v.Descripcion,v.Modulo,v.Programacion,v.PermiteManual,v.VentanaEsperadaMin
FROM (VALUES ('CLI_ARCHIVOS_HUERFANOS',N'Recoge archivos de clientes sin metadatos tras el periodo de gracia',
              'Clientes',N'Diaria',1,1440))
    v(Codigo,Descripcion,Modulo,Programacion,PermiteManual,VentanaEsperadaMin)
WHERE NOT EXISTS (SELECT 1 FROM Sistema.Tarea WHERE Codigo=v.Codigo);
COMMIT TRANSACTION;
