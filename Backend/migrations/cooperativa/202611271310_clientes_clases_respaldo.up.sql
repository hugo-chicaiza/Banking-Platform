/* E5-08: clases condicionales que se resuelven en la puerta de habilitación. */
SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57508, 'Falta confirmar la base destino de E5-08.', 1;

INSERT Catalogo.ClaseDocumentoCliente(Codigo, Nombre, ObligatorioNatural, ObligatorioJuridico)
SELECT v.Codigo, v.Nombre, 0, 0
FROM (VALUES ('PASAPORTE_DATOS', N'Pasaporte (página de datos)'),
             ('RESPALDO_TUTOR', N'Respaldo de tutor')) AS v(Codigo, Nombre)
WHERE NOT EXISTS (
    SELECT 1 FROM Catalogo.ClaseDocumentoCliente c WITH (UPDLOCK,HOLDLOCK)
    WHERE c.Codigo=v.Codigo
);
