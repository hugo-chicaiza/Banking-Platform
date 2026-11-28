-- #39 · E5-02 · Unicidad del correo principal y lista global de dominios.
SET XACT_ABORT ON;
SET ANSI_NULLS ON;
SET ANSI_PADDING ON;
SET ANSI_WARNINGS ON;
SET ARITHABORT ON;
SET CONCAT_NULL_YIELDS_NULL ON;
SET QUOTED_IDENTIFIER ON;
SET NUMERIC_ROUNDABORT OFF;

IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57190, 'Falta confirmar la base destino de la migracion.', 1;

BEGIN TRY
    BEGIN TRANSACTION;

    IF COL_LENGTH('Clientes.Cliente', 'Email') IS NULL
        OR OBJECT_ID('Parametros.Parametro', 'U') IS NULL
        OR OBJECT_ID('Parametros.ParametroValor', 'U') IS NULL
        THROW 57190, 'Faltan las dependencias del correo principal.', 1;

    IF EXISTS (
        SELECT 1
        FROM Clientes.Cliente WITH (TABLOCKX, HOLDLOCK)
        WHERE Email IS NOT NULL AND Email <> ''
        GROUP BY LOWER(LTRIM(RTRIM(Email))) COLLATE Latin1_General_100_BIN2
        HAVING COUNT_BIG(*) > 1
    )
        THROW 57190, 'Hay correos principales repetidos; revise el inventario antes de continuar.', 1;

    IF COL_LENGTH('Clientes.Cliente', 'EmailPrincipalNormalizado') IS NULL
        ALTER TABLE Clientes.Cliente ADD EmailPrincipalNormalizado AS (
            LOWER(LTRIM(RTRIM(Email))) COLLATE Latin1_General_100_BIN2
        ) PERSISTED;

    IF NOT EXISTS (
        SELECT 1 FROM sys.indexes
        WHERE object_id = OBJECT_ID('Clientes.Cliente') AND name = 'UX_Cliente_EmailPrincipal'
    )
        EXEC(N'CREATE UNIQUE INDEX UX_Cliente_EmailPrincipal
               ON Clientes.Cliente(EmailPrincipalNormalizado)
               WHERE Email IS NOT NULL AND Email <> '''';');

    INSERT Parametros.Parametro(Clave, Modulo, Descripcion, TipoDato, EsSensible, AdmiteAgencia)
    SELECT 'CLI_DOMINIOS_BLOQUEADOS', 'Clientes', N'Dominios bloqueados para el correo principal', 'Lista', 1, 0
    WHERE NOT EXISTS (
        SELECT 1 FROM Parametros.Parametro WITH (UPDLOCK, HOLDLOCK)
        WHERE Clave = 'CLI_DOMINIOS_BLOQUEADOS'
    );

    IF EXISTS (
        SELECT 1 FROM Parametros.Parametro
        WHERE Clave = 'CLI_DOMINIOS_BLOQUEADOS' AND (TipoDato <> 'Lista' OR AdmiteAgencia <> 0)
    )
        THROW 57190, 'El parametro de dominios debe ser una lista global.', 1;

    INSERT Parametros.ParametroValor(IdParametro, Valor, VigenciaDesde, CreadoPor)
    SELECT p.IdParametro, N'[]', '20200101', NULL
    FROM Parametros.Parametro p
    WHERE p.Clave = 'CLI_DOMINIOS_BLOQUEADOS'
      AND NOT EXISTS (
        SELECT 1 FROM Parametros.ParametroValor v WITH (UPDLOCK, HOLDLOCK)
        WHERE v.IdParametro = p.IdParametro
      );

    COMMIT TRANSACTION;
END TRY
BEGIN CATCH
    IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;
