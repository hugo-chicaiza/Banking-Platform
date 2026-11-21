/* Configurar SESSION_CONTEXT en ESTA conexión de SSMS, tras verificar el usuario
   en SeguridadDB. No hay un ID de usuario por defecto. Ver README.md.
   Fecha efectiva: día de ejecución en Ecuador, salvo fecha explícita de la carga.
   Reposición es opt-in y requiere 003 + integración del flujo aprobada. */
SET XACT_ABORT ON;
DECLARE @RegistradoPor int = TRY_CONVERT(int, SESSION_CONTEXT(N'e112.registrado_por'));
DECLARE @Fecha date = COALESCE(
    TRY_CONVERT(date, CONVERT(nvarchar(4000), SESSION_CONTEXT(N'e112.fecha_efectiva'))),
    CONVERT(date, SYSDATETIMEOFFSET() AT TIME ZONE 'SA Pacific Standard Time'));
DECLARE @Reposicion bit = COALESCE(TRY_CONVERT(bit, SESSION_CONTEXT(N'e112.incluir_reposicion')), 0);
IF @RegistradoPor IS NULL OR @RegistradoPor <= 0
    THROW 51104, 'Complete RegistradoPor con un UsuarioID real verificado en SeguridadDB.', 1;
IF SESSION_CONTEXT(N'e112.fecha_efectiva') IS NOT NULL
   AND TRY_CONVERT(date, CONVERT(nvarchar(4000), SESSION_CONTEXT(N'e112.fecha_efectiva'))) IS NULL
    THROW 51104, 'Fecha efectiva invalida.', 1;

DECLARE @Tarifas TABLE (Codigo varchar(30) PRIMARY KEY, IdCanal int, Canal varchar(10), IdComision int, Valor decimal(12,4));
/* TRF-WEB (0,20) se conserva en el catalogo para la futura transferencia
   interbancaria saliente WEB; Transferencia_Enviada tambien representa internas. */
INSERT @Tarifas VALUES ('Retiro',2,'ATM',1,0.45);
IF @Reposicion = 1 INSERT @Tarifas VALUES ('Reposicion_Tarjeta',1,'VENT',3,5.00);

BEGIN TRY
    BEGIN TRANSACTION;
    /* Bloqueo hasta COMMIT: serializa reejecuciones y escritores concurrentes. */
    DECLARE @Filas bigint;
    SELECT @Filas = COUNT_BIG(*) FROM Transacciones.ComisionTipoTransaccion WITH (TABLOCKX, HOLDLOCK);
    /* No corregir datos previos silenciosamente: identificar con la consulta
       del README y resolver mediante una correccion revisada por separado. */
    IF EXISTS (
        SELECT 1 FROM Transacciones.ComisionTipoTransaccion p
        JOIN Transacciones.Comisiones c ON c.IdComision=p.IdComision
        WHERE p.CodigoTipoTransaccion='Transferencia_Enviada' AND p.IdCanal=3
          AND (c.IdComision=2 OR c.CodigoComision='TRF-WEB') AND p.Estado='A'
          AND (p.VigenciaHasta IS NULL OR p.VigenciaHasta>@Fecha))
        THROW 51104, 'Asociacion incorrecta TRF-WEB con Transferencia_Enviada/WEB. Identificar con la consulta del README; no se modifico ni elimino. No se cargo nada.', 1;

    IF COALESCE(COLUMNPROPERTY(OBJECT_ID('Transacciones.ComisionTipoTransaccion'), 'IdComisionTipoTransaccion', 'IsIdentity'),0) <> 1
       AND NOT EXISTS (
           SELECT 1 FROM sys.columns c JOIN sys.default_constraints d ON d.object_id=c.default_object_id
           JOIN sys.sql_expression_dependencies dep ON dep.referencing_id=d.object_id
           JOIN sys.sequences s ON s.object_id=dep.referenced_id
           WHERE c.object_id=OBJECT_ID('Transacciones.ComisionTipoTransaccion') AND c.name='IdComisionTipoTransaccion')
        THROW 51104, 'ID sin IDENTITY ni DEFAULT de secuencia. Revisar generador; no usar MAX+1.', 1;

    IF EXISTS (
        SELECT 1 FROM @Tarifas t
        LEFT JOIN Canal.Canal ca WITH (HOLDLOCK) ON ca.IdCanal=t.IdCanal AND ca.CodigoCanal=t.Canal AND ca.Estado='A'
        LEFT JOIN Transacciones.TipoTransaccion tt WITH (HOLDLOCK) ON tt.CodigoTipo=t.Codigo AND tt.Estado='A'
        LEFT JOIN Transacciones.Comisiones c WITH (HOLDLOCK) ON c.IdComision=t.IdComision
            AND c.IdCanal=t.IdCanal AND c.TipoCalculo='Fijo' AND c.Estado='A'
        LEFT JOIN Transacciones.ComisionValor v WITH (HOLDLOCK)
            ON v.IdComision=c.IdComision AND v.Valor=t.Valor AND v.VigenciaDesde<=@Fecha
           AND (v.VigenciaHasta IS NULL OR v.VigenciaHasta>@Fecha)
        WHERE ca.IdCanal IS NULL OR tt.CodigoTipo IS NULL OR v.IdComision IS NULL)
        THROW 51104, 'Catalogos, canales, tarifa o vigencia distintos de lo esperado. No se cargo nada.', 1;

    /* Se conserva una asignación abierta equivalente que ya cubre la fecha.
       Cualquier otro intervalo activo que intersecte [@Fecha,infinito) aborta;
       no se cierran vigencias ni se reemplaza historia silenciosamente. */
    IF EXISTS (
        SELECT 1 FROM @Tarifas t JOIN Transacciones.ComisionTipoTransaccion p
            ON p.CodigoTipoTransaccion=t.Codigo AND p.IdCanal=t.IdCanal AND p.Estado='A'
        WHERE (p.VigenciaHasta IS NULL OR p.VigenciaHasta>@Fecha)
          AND NOT (p.IdComision=t.IdComision AND p.VigenciaDesde<=@Fecha AND p.VigenciaHasta IS NULL))
        THROW 51104, 'Existe una vigencia incompatible o futura. Resolver el conflicto antes de cargar.', 1;
    IF EXISTS (
        SELECT 1 FROM @Tarifas t JOIN Transacciones.ComisionTipoTransaccion p
            ON p.CodigoTipoTransaccion=t.Codigo AND p.IdCanal=t.IdCanal AND p.Estado='A'
        WHERE p.VigenciaDesde<=@Fecha AND (p.VigenciaHasta IS NULL OR p.VigenciaHasta>@Fecha)
        GROUP BY t.Codigo HAVING COUNT(*)>1)
        THROW 51104, 'Ya hay asignaciones activas duplicadas; resolver antes de cargar.', 1;

    INSERT Transacciones.ComisionTipoTransaccion
        (CodigoTipoTransaccion,IdCanal,IdComision,VigenciaDesde,VigenciaHasta,Estado,RegistradoPor)
    SELECT t.Codigo,t.IdCanal,t.IdComision,@Fecha,NULL,'A',@RegistradoPor FROM @Tarifas t
    WHERE NOT EXISTS (SELECT 1 FROM Transacciones.ComisionTipoTransaccion p
        WHERE p.CodigoTipoTransaccion=t.Codigo AND p.IdCanal=t.IdCanal AND p.IdComision=t.IdComision
          AND p.Estado='A' AND p.VigenciaDesde<=@Fecha AND p.VigenciaHasta IS NULL);
    COMMIT;
END TRY
BEGIN CATCH
    IF XACT_STATE() <> 0 ROLLBACK;
    THROW;
END CATCH;
SELECT p.* FROM Transacciones.ComisionTipoTransaccion p JOIN @Tarifas t
    ON t.Codigo=p.CodigoTipoTransaccion AND t.IdCanal=p.IdCanal ORDER BY p.IdComisionTipoTransaccion;
