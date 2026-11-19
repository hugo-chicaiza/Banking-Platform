-- Ejecutar antes y después del cambio en CooperativaDB y SeguridadDB.
-- Los bloques opcionales emiten únicamente SELECT.
SELECT DB_NAME() AS BaseActual, USER_NAME() AS UsuarioSQL,
       HAS_PERMS_BY_NAME(DB_NAME(), 'DATABASE', 'VIEW DEFINITION') AS VeDefiniciones;

IF OBJECT_ID(N'Transacciones.Comisiones', N'U') IS NOT NULL
BEGIN
    DECLARE @Fecha date =
        CONVERT(date, SYSDATETIMEOFFSET() AT TIME ZONE 'SA Pacific Standard Time');
    DECLARE @Cobrador int = OBJECT_ID(N'Transacciones.fn_CalcularComision');

    SELECT @Cobrador AS IdCobrador, OBJECT_DEFINITION(@Cobrador) AS DefinicionCobrador;
    SELECT p.parameter_id, p.name, TYPE_NAME(p.user_type_id) AS Tipo,
           p.max_length, p.precision, p.scale
    FROM sys.parameters AS p
    WHERE p.object_id = @Cobrador
    ORDER BY p.parameter_id;

    SELECT DISTINCT OBJECT_SCHEMA_NAME(d.referencing_id) AS Esquema,
           OBJECT_NAME(d.referencing_id) AS Consumidor,
           d.referenced_schema_name AS EsquemaReferido,
           d.referenced_entity_name AS ObjetoReferido,
           OBJECT_DEFINITION(d.referencing_id) AS Definicion
    FROM sys.sql_expression_dependencies AS d
    WHERE d.referenced_id IN (
        OBJECT_ID(N'Transacciones.Comisiones'), @Cobrador,
        OBJECT_ID(N'Transacciones.ComisionValor'),
        OBJECT_ID(N'Transacciones.vw_ComisionValorPresentacion')
    )
    ORDER BY Esquema, Consumidor, ObjetoReferido;

    -- Complemento para referencias textuales que no aparecen como dependencias.
    SELECT OBJECT_SCHEMA_NAME(m.object_id) AS Esquema,
           OBJECT_NAME(m.object_id) AS Objeto
    FROM sys.sql_modules AS m
    WHERE m.definition LIKE N'%Comisiones%'
       OR m.definition LIKE N'%fn_CalcularComision%'
    ORDER BY Esquema, Objeto;

    -- Exportar antes y después. Las comisiones base y sus IDs deben conservarse.
    SELECT IdComision, CodigoComision, IdCanal, Estado, TipoCalculo,
           Valor AS ValorInicial, VigenciaDesde, VigenciaHasta
    FROM Transacciones.Comisiones
    ORDER BY IdComision;

    -- Debe devolver cero filas. El seed se ejecuta antes del trigger porcentual.
    SELECT IdComision, CodigoComision, Valor, VigenciaDesde, VigenciaHasta
    FROM Transacciones.Comisiones
    WHERE Valor IS NULL OR Valor < 0 OR VigenciaDesde IS NULL
       OR (TipoCalculo = 'Porcentaje' AND Valor > 100)
       OR (VigenciaHasta IS NOT NULL AND VigenciaHasta <= VigenciaDesde);

    -- Comparar estas referencias y vigencias antes y después.
    EXEC sys.sp_executesql N'
        SELECT IdComisionTipoTransaccion, IdComision, CodigoTipoTransaccion,
               IdCanal, Estado, VigenciaDesde, VigenciaHasta
        FROM Transacciones.ComisionTipoTransaccion
        ORDER BY IdComisionTipoTransaccion;';
    IF OBJECT_ID(N'Transacciones.ExoneracionComision', N'U') IS NOT NULL
        EXEC sys.sp_executesql N'
            SELECT IdExoneracion, IdComision, Estado, VigenciaDesde, VigenciaHasta
            FROM Transacciones.ExoneracionComision ORDER BY IdExoneracion;';
    IF OBJECT_ID(N'ProductosFinancieros.ProductoComision', N'U') IS NOT NULL
        EXEC sys.sp_executesql N'
            SELECT IdComision, IdProducto, IdSubProducto, Estado
            FROM ProductosFinancieros.ProductoComision
            ORDER BY IdComision, IdProducto, IdSubProducto;';

    -- Ajustar este ejemplo a un evento y un canal conocidos.
    IF @Cobrador IS NOT NULL
        EXEC sys.sp_executesql N'
            SELECT @Dia AS Fecha, x.*
            FROM Transacciones.fn_CalcularComision(''Retiro'', 2, 100.00, @Dia) AS x;',
            N'@Dia date', @Fecha;

    IF OBJECT_ID(N'Transacciones.ComisionValor', N'U') IS NOT NULL
    BEGIN
        SELECT t.name, t.is_disabled
        FROM sys.triggers AS t
        WHERE t.object_id IN (
            OBJECT_ID(N'Transacciones.trg_ComisionValor_SinSolape'),
            OBJECT_ID(N'Transacciones.trg_Comisiones_ValorInicial')
        );

        SELECT i.name, i.is_unique, i.is_disabled, i.filter_definition
        FROM sys.indexes AS i
        WHERE i.object_id = OBJECT_ID(N'Transacciones.ComisionValor')
          AND i.name IN ('UX_ComisionValor_Inicio', 'UX_ComisionValor_Solicitud');

        EXEC sys.sp_executesql N'
            -- Resultado esperado para estas cuatro consultas: cero filas.
            SELECT c.IdComision AS ComisionSinVersion
            FROM Transacciones.Comisiones AS c
            WHERE NOT EXISTS (SELECT 1 FROM Transacciones.ComisionValor AS v
                              WHERE v.IdComision = c.IdComision);

            SELECT a.IdComision, a.IdComisionValor AS Version1, b.IdComisionValor AS Version2
            FROM Transacciones.ComisionValor AS a
            JOIN Transacciones.ComisionValor AS b
              ON b.IdComision = a.IdComision AND b.IdComisionValor > a.IdComisionValor
             AND (a.VigenciaHasta IS NULL OR b.VigenciaDesde < a.VigenciaHasta)
             AND (b.VigenciaHasta IS NULL OR a.VigenciaDesde < b.VigenciaHasta);

            SELECT v.IdComision, v.IdComisionValor, v.Valor
            FROM Transacciones.ComisionValor AS v
            JOIN Transacciones.Comisiones AS c ON c.IdComision = v.IdComision
            WHERE v.Valor < 0 OR (c.TipoCalculo = ''Porcentaje'' AND v.Valor > 100)
               OR (v.VigenciaHasta IS NOT NULL AND v.VigenciaHasta <= v.VigenciaDesde);

            SELECT IdSolicitud, COUNT_BIG(*) AS Versiones
            FROM Transacciones.ComisionValor WHERE IdSolicitud IS NOT NULL
            GROUP BY IdSolicitud HAVING COUNT_BIG(*) > 1;

            -- La tarifa calculada al corte puede diferir del valor inicial.
            SELECT c.IdComision, c.CodigoComision, c.Valor AS ValorInicial, v.Valor AS ValorAlCorte
            FROM Transacciones.Comisiones AS c
            LEFT JOIN Transacciones.ComisionValor AS v ON v.IdComision = c.IdComision
               AND v.VigenciaDesde <= @Dia AND (v.VigenciaHasta IS NULL OR v.VigenciaHasta > @Dia)
            ORDER BY c.IdComision;',
            N'@Dia date', @Fecha;
    END;
END;

IF OBJECT_ID(N'Seguridad.TransaccionesInterfaz', N'U') IS NOT NULL
BEGIN
    EXEC sys.sp_executesql N'
        SELECT CodigoTransaccion, BaseObjetivo, RolesEjecucion, PermisoAprobacion,
               EsSensible, Estado
        FROM Seguridad.TransaccionesInterfaz
        WHERE CodigoTransaccion IN (''PAR-EDITAR'', ''PAR-COMISION'')
        ORDER BY CodigoTransaccion;';
END;
