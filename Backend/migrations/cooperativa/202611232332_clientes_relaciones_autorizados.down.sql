/* No retira evidencia de relaciones o autorizaciones ya registradas. */
SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'')<>DB_NAME()
    THROW 57503, 'Falta confirmar la base destino.', 1;
BEGIN TRANSACTION;
IF NOT EXISTS (SELECT 1 FROM sys.extended_properties WHERE class=0 AND name=N'E601_AutorizadosPrevios'
    AND CONVERT(bit,value)=0)
    THROW 57503, 'No se puede retirar la estructura previa de autorizados. Usar respaldo.', 1;
IF OBJECT_ID('Cuentas.CuentaAutorizado','U') IS NOT NULL
    AND EXISTS(SELECT 1 FROM Cuentas.CuentaAutorizado WITH (TABLOCKX,HOLDLOCK))
    THROW 57503, 'Existen autorizados que deben conservarse.', 1;
IF OBJECT_ID('Clientes.ClienteRelacion','U') IS NOT NULL
    AND EXISTS(SELECT 1 FROM Clientes.ClienteRelacion WITH (TABLOCKX,HOLDLOCK))
    THROW 57503, 'Existen relaciones que deben conservarse.', 1;
DROP TABLE IF EXISTS Cuentas.CuentaAutorizado;
DROP TABLE IF EXISTS Clientes.ClienteRelacion;
IF OBJECT_ID('Catalogo.TipoRelacionCliente','U') IS NOT NULL
    AND EXISTS(SELECT 1 FROM Catalogo.TipoRelacionCliente
        WHERE Codigo NOT IN ('Tutor','RepresentanteLegal','Conyuge','Firmante','Referencia'))
    THROW 57503, 'El catálogo incluye tipos de relación añadidos posteriormente.', 1;
DROP TABLE IF EXISTS Catalogo.TipoRelacionCliente;
DELETE v FROM Parametros.ParametroValor AS v JOIN Parametros.Parametro AS p ON p.IdParametro=v.IdParametro
WHERE p.Clave='CLI_EDAD_MAYORIA' AND v.Valor='18' AND v.VigenciaDesde='20260101' AND v.CreadoPor IS NULL;
DELETE p FROM Parametros.Parametro AS p WHERE p.Clave='CLI_EDAD_MAYORIA'
    AND NOT EXISTS(SELECT 1 FROM Parametros.ParametroValor AS v WHERE v.IdParametro=p.IdParametro);
EXEC sys.sp_dropextendedproperty @name=N'E601_AutorizadosPrevios';
COMMIT TRANSACTION;
