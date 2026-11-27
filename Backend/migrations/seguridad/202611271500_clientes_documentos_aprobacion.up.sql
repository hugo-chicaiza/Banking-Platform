INSERT Seguridad.TransaccionesInterfaz
    (CodigoTransaccion, NombreTransaccion, Modulo, BaseObjetivo, RolesEjecucion, PermisoAprobacion, EsSensible, Estado)
VALUES
    ('CLI-DOCUMENTO', N'Cambiar documento principal', 'Clientes', 'cooperativa', N'["ADMIN","ASESOR"]', 'clientes:aprobar', 1, 'A'),
    ('CAT-EDITAR-DOCUMENTO', N'Configurar tipo de documento', 'Catalogos', 'cooperativa', N'["ADMIN"]', 'parametros:aprobar', 1, 'A');
