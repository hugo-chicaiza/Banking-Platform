-- #102. Alta del auxiliar de faltantes ATM. No reclasifica saldos históricos.
SET NOCOUNT ON;
SET XACT_ABORT ON;

IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57930, N'Confirme la base de la migración de faltantes ATM.', 1;
IF @@TRANCOUNT <> 0
    THROW 57931, N'Ejecute la migración sin una transacción previa.', 1;

BEGIN TRY
    BEGIN TRANSACTION;

    DECLARE @padre int, @auxiliar int;
    SELECT @padre = c.IdCuentaContable
    FROM Contabilidad.CuentasContables c WITH (UPDLOCK, HOLDLOCK)
    JOIN Contabilidad.CuentasContables mayor WITH (HOLDLOCK)
      ON mayor.IdCuentaContable = c.IdCuentaSuperior AND mayor.CodigoCuenta = '1990'
    WHERE c.CodigoCuenta = '199025' AND c.Naturaleza = 'DEUDORA'
      AND c.Estado = 1 AND c.EsImputable = 0 AND c.EsCuentaValuacion = 0
      AND c.EsCatalogoRegulador = 1;
    IF @padre IS NULL
        THROW 57932, N'199025 debe ser una subcuenta deudora, activa y no imputable.', 1;

    SELECT @auxiliar = IdCuentaContable
    FROM Contabilidad.CuentasContables WITH (UPDLOCK, HOLDLOCK)
    WHERE CodigoCuenta = '19902515';
    IF @auxiliar IS NULL
    BEGIN
        INSERT Contabilidad.CuentasContables
            (CodigoCuenta, NombreCuenta, IdCuentaSuperior, Naturaleza, Estado,
             EsImputable, EsCuentaValuacion, EsCatalogoRegulador, SoloAutomatica, Saldo)
        VALUES ('19902515', N'Faltantes de cajeros automáticos', @padre, 'DEUDORA',
                1, 1, 0, 0, 0, 0);
        SELECT @auxiliar = IdCuentaContable FROM Contabilidad.CuentasContables
        WHERE CodigoCuenta = '19902515';
    END;

    IF NOT EXISTS (
        SELECT 1 FROM Contabilidad.CuentasContables c
        WHERE c.IdCuentaContable = @auxiliar AND c.IdCuentaSuperior = @padre
          AND c.Naturaleza = 'DEUDORA' AND c.Estado = 1 AND c.EsImputable = 1
          AND c.EsCuentaValuacion = 0 AND c.EsCatalogoRegulador = 0 AND c.SoloAutomatica = 0
          AND NOT EXISTS (
              SELECT 1 FROM Contabilidad.CuentasContables h WITH (HOLDLOCK)
              WHERE h.IdCuentaSuperior = c.IdCuentaContable
          )
    )
        THROW 57933, N'19902515 existe con una configuración incompatible.', 1;

    -- Un reintento admite uso previo trazable de la propia regla. Cualquier
    -- otro uso (incluidas regularizaciones históricas) requiere revisión.
    IF EXISTS (
        SELECT 1 FROM Contabilidad.MovimientosContables m WITH (HOLDLOCK)
        LEFT JOIN Contabilidad.AsientoContable a ON a.IdAsientoContable = m.IdAsientoContable
        LEFT JOIN Contabilidad.PlantillaAsiento p ON p.IdPlantillaAsiento = a.IdPlantillaAsiento
        LEFT JOIN Contabilidad.TiposAsiento t ON t.IdTipoAsiento = a.IdTipoAsiento
        WHERE m.IdCuentaContable = @auxiliar
          AND (COALESCE(p.CodigoPlantilla, '') <> 'ATM_FALTANTE'
               OR COALESCE(t.Codigo, '') <> 'ATM_FALTANTE'
               OR t.EsManual <> 0 OR m.TipoMovimiento <> 'DEBITO')
    )
        THROW 57934, N'19902515 tiene movimientos ajenos a la regla ATM_FALTANTE.', 1;

    IF EXISTS (
        SELECT 1 FROM Contabilidad.CuentasContables c
        WHERE c.IdCuentaContable = @auxiliar AND c.Saldo <> 0
          AND NOT EXISTS (
              SELECT 1 FROM Contabilidad.MovimientosContables m WITH (HOLDLOCK)
              WHERE m.IdCuentaContable = c.IdCuentaContable
          )
    )
        THROW 57935, N'19902515 tiene saldo sin movimientos que lo sustenten.', 1;

    COMMIT;
END TRY
BEGIN CATCH
    IF XACT_STATE() <> 0 ROLLBACK;
    THROW;
END CATCH;
