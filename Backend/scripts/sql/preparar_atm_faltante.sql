-- Solo lectura. Defina atm_faltante_vigencia en SESSION_CONTEXT.
SET NOCOUNT ON;

DECLARE @vigencia date = TRY_CONVERT(date, SESSION_CONTEXT(N'atm_faltante_vigencia'));
DECLARE @ahora datetime2 =
    CAST(SYSDATETIMEOFFSET() AT TIME ZONE 'SA Pacific Standard Time' AS datetime2);
DECLARE @efectiva date;
SELECT @efectiva = Fecha FROM Contabilidad.FechaContable
WHERE IdFechaContable = Contabilidad.fn_IdFechaContable(@ahora);

IF @efectiva IS NULL OR @vigencia IS NULL OR @vigencia <= @efectiva
   OR NOT EXISTS (
       SELECT 1 FROM Contabilidad.FechaContable WHERE Fecha = @vigencia AND EsDiaContable = 1
   )
    THROW 57936, N'Indique un día hábil posterior a la fecha contable efectiva.', 1;
IF EXISTS (SELECT 1 FROM Contabilidad.PlantillaAsiento WHERE CodigoPlantilla = 'ATM_FALTANTE')
    THROW 57937, N'ATM_FALTANTE ya existe. Revise el historial antes de registrar.', 1;

DECLARE @tipo int, @concepto int, @debe int, @haber int;
SELECT @tipo = IdTipoAsiento FROM Contabilidad.TiposAsiento
WHERE Codigo = 'ATM_FALTANTE' AND Estado = 'A' AND EsManual = 0;
SELECT @concepto = IdConceptoContable FROM Contabilidad.ConceptoContable
WHERE CodigoConcepto = 'AJUSTE_FALTANTE' AND Estado = 'Activo';

SELECT @debe = MAX(CASE WHEN c.CodigoCuenta = '19902515' AND p.CodigoCuenta = '199025'
                         AND p.Estado = 1 AND p.EsImputable = 0 AND p.Naturaleza = 'DEUDORA'
                        THEN c.IdCuentaContable END),
       @haber = MAX(CASE WHEN c.CodigoCuenta = '11010515' THEN c.IdCuentaContable END)
FROM Contabilidad.CuentasContables c
LEFT JOIN Contabilidad.CuentasContables p ON p.IdCuentaContable = c.IdCuentaSuperior
WHERE c.CodigoCuenta IN ('19902515', '11010515')
  AND c.Estado = 1 AND c.EsImputable = 1 AND c.Naturaleza = 'DEUDORA'
  AND c.EsCuentaValuacion = 0
  AND (c.CodigoCuenta <> '19902515' OR (c.SoloAutomatica = 0 AND c.EsCatalogoRegulador = 0))
  AND NOT EXISTS (
      SELECT 1 FROM Contabilidad.CuentasContables h WHERE h.IdCuentaSuperior = c.IdCuentaContable
  );

IF @tipo IS NULL OR @concepto IS NULL OR @debe IS NULL OR @haber IS NULL
    THROW 57938, N'Falta el tipo automático, concepto activo o una cuenta hoja de ATM.', 1;

DECLARE @lineas nvarchar(max) = (
    SELECT l.Lado AS lado, 'DIFERENCIA' AS base, 'FIJA' AS origen, l.Cuenta AS cuenta
    FROM (VALUES (1, 'DEBITO', @debe), (2, 'CREDITO', @haber)) l(Orden, Lado, Cuenta)
    ORDER BY l.Orden FOR JSON PATH
);
DECLARE @borrador nvarchar(max) = (
    SELECT 'ATM_FALTANTE' AS codigoPlantilla, @concepto AS idConceptoContable,
           CONVERT(char(10), @vigencia, 23) AS vigenciaDesde,
           N'Faltante aprobado de ATM' AS nombre, JSON_QUERY(@lineas) AS lineas
    FOR JSON PATH, WITHOUT_ARRAY_WRAPPER
);

SELECT @efectiva AS FechaContableEfectiva, @vigencia AS VigenciaPropuesta, (
    SELECT @tipo AS idTipoAsiento,
           JSON_QUERY(@borrador) AS borrador
    FOR JSON PATH
) AS ManifiestoJSON,
(
    SELECT JSON_QUERY(@lineas) AS lineas, CAST(50.00 AS decimal(18,2)) AS [montos.DIFERENCIA]
    FOR JSON PATH, WITHOUT_ARRAY_WRAPPER
) AS SimulacionSwaggerJSON,
JSON_MODIFY(@borrador, '$.soloPrimeraVersion', CAST(1 AS bit)) AS RegistroSwaggerJSON;
