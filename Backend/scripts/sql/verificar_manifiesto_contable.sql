/* Solo lectura. Pegue el JSON emitido por preparar_paquete_contable.sql.
   Distingue borrador, versión aprobada seleccionable y diferencias. */
SET NOCOUNT ON;
DECLARE @Manifiesto nvarchar(max) = N'[]';
IF ISJSON(@Manifiesto) <> 1 OR LEFT(LTRIM(@Manifiesto),1) <> '['
    THROW 57900, N'El manifiesto debe ser un arreglo JSON.', 1;

DECLARE @esperadas TABLE (
    Codigo varchar(50) PRIMARY KEY, Tipo int NOT NULL, Concepto int NOT NULL,
    Vigencia date NOT NULL, Lineas nvarchar(max) NOT NULL
);
INSERT @esperadas
SELECT Codigo,Tipo,Concepto,Vigencia,Lineas
FROM OPENJSON(@Manifiesto) WITH (
    Codigo varchar(50) '$.borrador.codigoPlantilla', Tipo int '$.idTipoAsiento',
    Concepto int '$.borrador.idConceptoContable', Vigencia date '$.borrador.vigenciaDesde',
    Lineas nvarchar(max) '$.borrador.lineas' AS JSON
);
IF NOT EXISTS (SELECT 1 FROM @esperadas)
    THROW 57901, N'Pegue un manifiesto con al menos una familia.', 1;

SELECT e.Codigo,e.Tipo,e.Concepto,e.Vigencia,
       p.IdPlantillaAsiento,p.Version,p.CreadoPor,p.AprobadoPor,p.FechaAprobacion,
       vigente.IdPlantillaAsiento AS IdSeleccionadaEnInicio,
       CASE WHEN candidatos.Total=0 THEN 'SIN_VERSION_EN_FECHA'
            WHEN candidatos.Total<>1 THEN 'VERSION_AMBIGUA'
            WHEN p.IdTipoAsiento<>e.Tipo OR p.IdConceptoContable<>e.Concepto THEN 'METADATOS_DISTINTOS'
            WHEN t.Estado<>'A' OR t.EsManual<>0 OR COALESCE(co.Estado,'')<>'Activo' THEN 'CATALOGO_INCOMPATIBLE'
            WHEN diferencias.Total<>0 THEN 'LINEAS_DISTINTAS'
            WHEN p.Estado=0 THEN 'BORRADOR'
            WHEN p.AprobadoPor IS NULL OR p.CreadoPor IS NULL OR p.AprobadoPor=p.CreadoPor
                THEN 'APROBACION_NO_VERIFICADA'
            WHEN vigente.IdPlantillaAsiento IS NULL OR vigente.IdPlantillaAsiento<>p.IdPlantillaAsiento
                THEN 'APROBADA_NO_SELECCIONADA'
            ELSE 'APROBADA_Y_SELECCIONADA' END AS Resultado
FROM @esperadas e
CROSS APPLY (SELECT COUNT(*) Total FROM Contabilidad.PlantillaAsiento f
             WHERE f.CodigoPlantilla=e.Codigo AND f.VigenciaDesde=e.Vigencia) candidatos
OUTER APPLY (
    SELECT TOP (1) f.*
    FROM Contabilidad.PlantillaAsiento f
    WHERE f.CodigoPlantilla=e.Codigo AND f.VigenciaDesde=e.Vigencia
    ORDER BY f.Version DESC
) p
LEFT JOIN Contabilidad.TiposAsiento t ON t.IdTipoAsiento=p.IdTipoAsiento
LEFT JOIN Contabilidad.ConceptoContable co ON co.IdConceptoContable=p.IdConceptoContable
OUTER APPLY (
    SELECT TOP (1) f.IdPlantillaAsiento FROM Contabilidad.PlantillaAsiento f
    JOIN Contabilidad.TiposAsiento tf ON tf.IdTipoAsiento=f.IdTipoAsiento
    WHERE f.CodigoPlantilla=e.Codigo AND f.Estado=1 AND tf.Estado='A' AND tf.EsManual=0
      AND f.VigenciaDesde<=e.Vigencia AND (f.VigenciaHasta IS NULL OR f.VigenciaHasta>=e.Vigencia)
    ORDER BY f.VigenciaDesde DESC,f.Version DESC
) vigente
CROSS APPLY (
    SELECT COUNT_BIG(*) Total
    FROM (
        SELECT CONVERT(int,j.[key])+1 AS Orden,l.Lado,l.Base,l.Origen,l.Cuenta,l.Rol
        FROM OPENJSON(e.Lineas) j
        CROSS APPLY OPENJSON(j.value) WITH (
            Lado varchar(7) '$.lado', Base varchar(15) '$.base', Origen varchar(15) '$.origen',
            Cuenta int '$.cuenta', Rol varchar(30) '$.rol'
        ) l
    ) x
    FULL OUTER JOIN (
        SELECT d.Orden,d.TipoMovimiento,d.ComponenteImporte,d.OrigenCuenta,d.IdCuentaContable,d.CodigoRol
        FROM Contabilidad.PlantillaAsientoDetalle d WHERE d.IdPlantillaAsiento=p.IdPlantillaAsiento
    ) d ON x.Orden=d.Orden
    WHERE x.Orden IS NULL OR d.Orden IS NULL OR EXISTS (
        SELECT x.Lado,x.Base,x.Origen,x.Cuenta,x.Rol
        EXCEPT
        SELECT d.TipoMovimiento,d.ComponenteImporte,d.OrigenCuenta,d.IdCuentaContable,d.CodigoRol
    )
) diferencias
ORDER BY e.Codigo;
