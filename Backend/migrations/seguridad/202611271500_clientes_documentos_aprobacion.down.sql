IF EXISTS (
    SELECT 1 FROM Seguridad.SolicitudAprobacion
    WHERE CodigoTransaccion IN ('CLI-DOCUMENTO', 'CAT-EDITAR-DOCUMENTO')
)
    THROW 50042, 'La reversión requiere preservar las solicitudes registradas.', 1;

DELETE Seguridad.TransaccionesInterfaz
WHERE CodigoTransaccion IN ('CLI-DOCUMENTO', 'CAT-EDITAR-DOCUMENTO');
