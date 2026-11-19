-- Ejecutar después de 001 y antes del backend. Conserva los IDs y filas originales.
SET NOCOUNT ON;
SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57280, N'Confirme la base cooperativa en migration_database.', 1;
BEGIN TRY
    BEGIN TRANSACTION;
    IF OBJECT_ID(N'Transacciones.Comisiones', N'U') IS NULL
       OR OBJECT_ID(N'Transacciones.fn_CalcularComision', N'IF') IS NULL
        THROW 57280, N'Falta el esquema de comisiones o su cálculo SQL legado.', 1;

    DECLARE @FuncionNueva nvarchar(max) = N'
    CREATE OR ALTER FUNCTION Transacciones.fn_CalcularComision
        (@CodigoTipo varchar(30), @IdCanal int, @Monto decimal(18,2), @Fecha date)
    RETURNS TABLE AS RETURN
        SELECT c.IdComision, c.CodigoComision,
               CAST(CASE WHEN c.TipoCalculo = ''Fijo'' THEN v.Valor
                         WHEN @Monto * v.Valor / 100 < c.MontoMinimo THEN c.MontoMinimo
                         WHEN @Monto * v.Valor / 100 > c.MontoMaximo THEN c.MontoMaximo
                         ELSE ROUND(@Monto * v.Valor / 100, 2) END AS decimal(18,2)) AS MontoComision
        FROM Transacciones.ComisionTipoTransaccion AS p
        JOIN Transacciones.Comisiones AS c ON c.IdComision = p.IdComision
        JOIN Transacciones.ComisionValor AS v ON v.IdComision = c.IdComision
        WHERE p.CodigoTipoTransaccion = @CodigoTipo AND p.IdCanal = @IdCanal
          AND p.Estado = ''A'' AND c.Estado = ''A''
          AND p.VigenciaDesde <= @Fecha AND (p.VigenciaHasta IS NULL OR p.VigenciaHasta > @Fecha)
          AND v.VigenciaDesde <= @Fecha AND (v.VigenciaHasta IS NULL OR v.VigenciaHasta > @Fecha);';
    DECLARE @FuncionLegada nvarchar(max) = N'CREATE   FUNCTION Transacciones.fn_CalcularComision
        (@CodigoTipo varchar(30), @IdCanal int, @Monto decimal(18,2), @Fecha date)
    RETURNS TABLE
    AS
    /* TR-04: comisiones parametrizadas para un tipo de transacción en un canal, con su valor
       calculado: Fijo = Valor; Porcentaje = Monto x Valor / 100 dentro de [MontoMinimo, MontoMaximo]. */
    RETURN
        SELECT c.IdComision, c.CodigoComision,
               CAST(CASE WHEN c.TipoCalculo = ''Fijo'' THEN c.Valor
                         WHEN @Monto * c.Valor / 100 < c.MontoMinimo THEN c.MontoMinimo
                         WHEN @Monto * c.Valor / 100 > c.MontoMaximo THEN c.MontoMaximo
                         ELSE ROUND(@Monto * c.Valor / 100, 2) END AS decimal(18,2)) AS MontoComision
        FROM Transacciones.ComisionTipoTransaccion p
        JOIN Transacciones.Comisiones c ON c.IdComision = p.IdComision
        WHERE p.CodigoTipoTransaccion = @CodigoTipo AND p.IdCanal = @IdCanal AND p.Estado = ''A'' AND c.Estado = ''A''
          AND p.VigenciaDesde <= @Fecha AND (p.VigenciaHasta IS NULL OR p.VigenciaHasta > @Fecha)
          AND c.VigenciaDesde <= @Fecha AND (c.VigenciaHasta IS NULL OR c.VigenciaHasta > @Fecha);';
    DECLARE @IdVersiones int = OBJECT_ID(N'Transacciones.ComisionValor', N'U');
    DECLARE @FuncionActual nvarchar(max) =
        OBJECT_DEFINITION(OBJECT_ID(N'Transacciones.fn_CalcularComision', N'IF'));
    DECLARE @FuncionEsperada nvarchar(max) =
        CASE WHEN @IdVersiones IS NULL THEN @FuncionLegada ELSE @FuncionNueva END;
    -- SQL Server puede guardar el prefijo DDL como CREATE o ALTER.
    -- Se compara desde FUNCTION, conservando el cuerpo con colacion binaria.
    SET @FuncionActual = SUBSTRING(@FuncionActual, NULLIF(CHARINDEX(N'FUNCTION ', @FuncionActual), 0), LEN(@FuncionActual));
    SET @FuncionEsperada = SUBSTRING(@FuncionEsperada, CHARINDEX(N'FUNCTION ', @FuncionEsperada), LEN(@FuncionEsperada));
    SET @FuncionActual = TRIM(REPLACE(REPLACE(REPLACE(@FuncionActual, CHAR(13), ''), CHAR(10), ' '), CHAR(9), ' '));
    SET @FuncionEsperada = TRIM(REPLACE(REPLACE(REPLACE(@FuncionEsperada, CHAR(13), ''), CHAR(10), ' '), CHAR(9), ' '));
    IF @FuncionActual IS NULL OR @FuncionActual COLLATE Latin1_General_100_BIN2
        <> @FuncionEsperada COLLATE Latin1_General_100_BIN2
        THROW 57287, N'Funcion de comisiones inesperada o estado de migracion parcial.', 1;

    IF @IdVersiones IS NOT NULL AND (
        OBJECT_ID(N'Transacciones.vw_ComisionValorPresentacion', N'V') IS NULL
        OR NOT EXISTS (SELECT 1 FROM sys.triggers WHERE object_id =
            OBJECT_ID(N'Transacciones.trg_ComisionValor_SinSolape') AND parent_id = @IdVersiones
            AND is_disabled = 0)
        OR NOT EXISTS (SELECT 1 FROM sys.triggers WHERE object_id =
            OBJECT_ID(N'Transacciones.trg_Comisiones_ValorInicial') AND parent_id =
            OBJECT_ID(N'Transacciones.Comisiones') AND is_disabled = 0)
        OR NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id = @IdVersiones
            AND name = 'UX_ComisionValor_Inicio' AND is_unique = 1 AND is_disabled = 0)
        OR NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id = @IdVersiones
            AND name = 'UX_ComisionValor_Solicitud' AND is_unique = 1 AND is_disabled = 0)
        OR NOT EXISTS (SELECT 1 FROM sys.check_constraints WHERE parent_object_id = @IdVersiones
            AND name = 'CK_ComisionValor_Intervalo' AND is_disabled = 0 AND is_not_trusted = 0)
        OR NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE parent_object_id = @IdVersiones
            AND referenced_object_id = OBJECT_ID(N'Transacciones.Comisiones')
            AND is_disabled = 0 AND is_not_trusted = 0 AND delete_referential_action = 0)
    )
        THROW 57288, N'Faltan objetos o restricciones del versionado de comisiones.', 1;

    IF OBJECT_ID(N'Transacciones.ComisionValor', N'U') IS NULL
    BEGIN
        CREATE TABLE Transacciones.ComisionValor (
            IdComisionValor bigint IDENTITY PRIMARY KEY,
            IdComision int NOT NULL REFERENCES Transacciones.Comisiones(IdComision),
            Valor decimal(12,4) NOT NULL CHECK (Valor >= 0),
            VigenciaDesde date NOT NULL,
            VigenciaHasta date NULL,
            IdSolicitud bigint NULL,
            CONSTRAINT CK_ComisionValor_Intervalo CHECK (VigenciaHasta IS NULL OR VigenciaHasta > VigenciaDesde),
            CONSTRAINT UX_ComisionValor_Inicio UNIQUE (IdComision, VigenciaDesde)
        );
        CREATE UNIQUE INDEX UX_ComisionValor_Solicitud
            ON Transacciones.ComisionValor(IdSolicitud) WHERE IdSolicitud IS NOT NULL;
        INSERT Transacciones.ComisionValor (IdComision, Valor, VigenciaDesde, VigenciaHasta)
        SELECT IdComision, Valor, VigenciaDesde, VigenciaHasta
        FROM Transacciones.Comisiones WITH (TABLOCKX, HOLDLOCK);
    END;

    EXEC sys.sp_executesql N'
        IF EXISTS (
            SELECT 1 FROM Transacciones.Comisiones AS c WITH (TABLOCKX, HOLDLOCK)
            WHERE NOT EXISTS (
                SELECT 1 FROM Transacciones.ComisionValor AS v WITH (TABLOCKX, HOLDLOCK)
                WHERE v.IdComision = c.IdComision AND v.IdSolicitud IS NULL
                  AND v.VigenciaDesde = c.VigenciaDesde AND v.Valor = c.Valor
            )
        )
            THROW 57289, N''Falta la version inicial de una comision.'', 1;

        IF EXISTS (
            SELECT 1
            FROM (
                SELECT v.*, LEAD(v.VigenciaDesde) OVER (
                    PARTITION BY v.IdComision ORDER BY v.VigenciaDesde
                ) AS Siguiente
                FROM Transacciones.ComisionValor AS v WITH (TABLOCKX, HOLDLOCK)
            ) AS v
            LEFT JOIN Transacciones.Comisiones AS c ON c.IdComision = v.IdComision
            WHERE c.IdComision IS NULL OR v.Valor < 0
              OR (c.TipoCalculo = ''Porcentaje'' AND v.Valor > 100)
              OR v.VigenciaDesde < c.VigenciaDesde
              OR (v.IdSolicitud IS NULL AND v.VigenciaDesde <> c.VigenciaDesde)
              OR (v.VigenciaHasta IS NOT NULL AND v.VigenciaHasta <= v.VigenciaDesde)
              OR (v.Siguiente IS NOT NULL AND
                   (v.VigenciaHasta IS NULL OR v.VigenciaHasta <> v.Siguiente))
              OR (v.Siguiente IS NULL AND (
                    v.VigenciaHasta <> c.VigenciaHasta
                    OR (v.VigenciaHasta IS NULL AND c.VigenciaHasta IS NOT NULL)
                    OR (v.VigenciaHasta IS NOT NULL AND c.VigenciaHasta IS NULL)
              ))
        )
            THROW 57290, N''El historial contiene tarifas o intervalos incompatibles, solapados o discontinuos.'', 1;
    ';

    EXEC sys.sp_executesql N'
    CREATE OR ALTER TRIGGER Transacciones.trg_ComisionValor_SinSolape
    ON Transacciones.ComisionValor AFTER INSERT, UPDATE AS
    BEGIN
        SET NOCOUNT ON;
        IF EXISTS (
            SELECT 1 FROM inserted AS i
            JOIN Transacciones.Comisiones AS c ON c.IdComision = i.IdComision
            WHERE c.TipoCalculo = ''Porcentaje'' AND i.Valor > 100
        )
            THROW 57283, N''La tarifa porcentual no puede exceder 100.'', 1;
        IF EXISTS (
            SELECT 1 FROM inserted AS i
            JOIN Transacciones.ComisionValor AS v WITH (UPDLOCK, HOLDLOCK)
              ON v.IdComision = i.IdComision AND v.IdComisionValor <> i.IdComisionValor
             AND (i.VigenciaHasta IS NULL OR v.VigenciaDesde < i.VigenciaHasta)
             AND (v.VigenciaHasta IS NULL OR i.VigenciaDesde < v.VigenciaHasta)
        )
            THROW 57281, N''Las vigencias de una comisión no pueden solaparse.'', 1;
    END;';

    EXEC sys.sp_executesql N'
    CREATE OR ALTER TRIGGER Transacciones.trg_Comisiones_ValorInicial
    ON Transacciones.Comisiones AFTER INSERT, UPDATE AS
    BEGIN
        SET NOCOUNT ON;
        IF EXISTS (
            SELECT i.IdComision, i.Valor, i.VigenciaDesde, i.VigenciaHasta
            FROM inserted AS i JOIN deleted AS d ON d.IdComision = i.IdComision
            EXCEPT SELECT IdComision, Valor, VigenciaDesde, VigenciaHasta FROM deleted
        )
            THROW 57282, N''Use el flujo de aprobación para modificar la tarifa.'', 1;
        INSERT Transacciones.ComisionValor (IdComision, Valor, VigenciaDesde, VigenciaHasta)
        SELECT i.IdComision, i.Valor, i.VigenciaDesde, i.VigenciaHasta
        FROM inserted AS i WHERE NOT EXISTS (
            SELECT 1 FROM deleted AS d WHERE d.IdComision = i.IdComision
        );
    END;';

    EXEC sys.sp_executesql N'
    CREATE OR ALTER VIEW Transacciones.vw_ComisionValorPresentacion AS
    SELECT c.IdComision, v.Valor, v.VigenciaDesde, v.VigenciaHasta
    FROM Transacciones.Comisiones AS c
    CROSS APPLY (VALUES (CONVERT(date, SYSDATETIMEOFFSET() AT TIME ZONE ''SA Pacific Standard Time''))) AS h(Hoy)
    CROSS APPLY (
        SELECT TOP (1) v.Valor, v.VigenciaDesde, v.VigenciaHasta
        FROM Transacciones.ComisionValor AS v
        WHERE v.IdComision = c.IdComision
        ORDER BY CASE WHEN v.VigenciaDesde <= h.Hoy THEN 0 ELSE 1 END,
                 CASE WHEN v.VigenciaDesde <= h.Hoy THEN v.VigenciaDesde END DESC,
                 v.VigenciaDesde
    ) AS v;';

    EXEC sys.sp_executesql @FuncionNueva;
    COMMIT TRANSACTION;
END TRY
BEGIN CATCH
    IF @@TRANCOUNT > 0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;
