-- Solo lectura. Ejecutar sobre CooperativaDB tras validar esquema E2/E3/E4.
DECLARE @Desde date = NULL; -- Acotar el periodo de asientos a investigar.

-- Evidencia de uso. La fecha de cada asiento se confronta con la versión que referencia.
SELECT p.CodigoPlantilla, p.Version, p.Estado, p.VigenciaDesde, p.VigenciaHasta,
       COUNT_BIG(a.IdAsientoContable) AS AsientosVinculados,
       MIN(a.FechaAsiento) AS PrimerUso, MAX(a.FechaAsiento) AS UltimoUso,
       SUM(CASE WHEN a.FechaAsiento < p.VigenciaDesde OR a.FechaAsiento > p.VigenciaHasta
                OR a.IdTipoAsiento <> p.IdTipoAsiento THEN 1 ELSE 0 END) AS RevisarVinculo
FROM Contabilidad.PlantillaAsiento p
LEFT JOIN Contabilidad.AsientoContable a ON a.IdPlantillaAsiento = p.IdPlantillaAsiento
    AND (@Desde IS NULL OR a.FechaAsiento >= @Desde)
GROUP BY p.CodigoPlantilla, p.Version, p.Estado, p.VigenciaDesde, p.VigenciaHasta
ORDER BY p.CodigoPlantilla, p.Version;

-- Tipo y origen ayudan a distinguir el adaptador BOV, asientos manuales, reversos e históricos.
SELECT a.Origen, t.Codigo, t.EsManual, a.Estado,
       CASE WHEN a.IdPlantillaAsiento IS NOT NULL THEN 'CON_VERSION'
            WHEN a.ClaveEventoContable IS NOT NULL THEN 'EVENTO_SIN_VERSION'
            ELSE 'SIN_VERSION_NI_CLAVE' END AS Evidencia, COUNT_BIG(*) AS Asientos
FROM Contabilidad.AsientoContable a
LEFT JOIN Contabilidad.TiposAsiento t ON t.IdTipoAsiento = a.IdTipoAsiento
WHERE @Desde IS NULL OR a.FechaAsiento >= @Desde
GROUP BY a.Origen, t.Codigo, t.EsManual, a.Estado,
         CASE WHEN a.IdPlantillaAsiento IS NOT NULL THEN 'CON_VERSION'
              WHEN a.ClaveEventoContable IS NOT NULL THEN 'EVENTO_SIN_VERSION'
              ELSE 'SIN_VERSION_NI_CLAVE' END
ORDER BY a.Origen, t.Codigo, Evidencia;

-- Toda comisión con cuenta ausente o inválida requiere clasificar su tarifa y vigencia.
SELECT co.IdComision, co.IdCuentaContableIngreso, c.CodigoCuenta, c.Estado, c.EsImputable
FROM Transacciones.Comisiones co
LEFT JOIN Contabilidad.CuentasContables c ON c.IdCuentaContable = co.IdCuentaContableIngreso
WHERE c.IdCuentaContable IS NULL OR c.Estado <> 1 OR c.EsImputable <> 1
   OR EXISTS (SELECT 1 FROM Contabilidad.CuentasContables h WHERE h.IdCuentaSuperior = c.IdCuentaContable);

-- Configuración confirmada y candidatas. Cuenta hoja de seis u ocho dígitos según su rama.
SELECT e.CodigoCuenta, e.Uso, c.IdCuentaContable, c.Estado, c.EsImputable, c.SoloAutomatica,
       p.CodigoCuenta AS Padre,
       CASE WHEN c.IdCuentaContable IS NULL THEN 'AUSENTE'
            WHEN c.Estado <> 1 OR c.EsImputable <> 1 OR EXISTS
              (SELECT 1 FROM Contabilidad.CuentasContables h WHERE h.IdCuentaSuperior=c.IdCuentaContable)
              THEN 'NO_HABILITADA' ELSE 'HOJA_HABILITADA' END AS Validacion
FROM (VALUES ('11010505','BOVEDA'), ('11010510','VENTANILLA'), ('11010515','ATM'),
             ('19080505','TRANSITO CONFIRMADO'), ('19902505','FALTANTES'),
             ('299005','CUC SOBRANTES'), ('549005','INGRESO DE TARIFAS A REVISAR')) e(CodigoCuenta,Uso)
LEFT JOIN Contabilidad.CuentasContables c ON c.CodigoCuenta=e.CodigoCuenta
LEFT JOIN Contabilidad.CuentasContables p ON p.IdCuentaContable=c.IdCuentaSuperior;
