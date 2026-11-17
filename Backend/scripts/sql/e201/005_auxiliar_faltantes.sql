/* #371. Subcuenta CUC Segmento 1 y auxiliar identificados explícitamente.
   Separado del corte de efectivo y ahorro. Conserva el saldo propio histórico. */
SET XACT_ABORT ON;
BEGIN TRY
    BEGIN TRANSACTION;
    DECLARE @Mayor int, @Subcuenta int;
    SELECT @Mayor=IdCuentaContable FROM Contabilidad.CuentasContables WITH (UPDLOCK,HOLDLOCK)
    WHERE CodigoCuenta='1990' AND Estado=1;
    IF @Mayor IS NULL THROW 56330,N'Falta el mayor CUC 1990 activo.',1;

    IF NOT EXISTS (SELECT 1 FROM Contabilidad.CuentasContables WITH (UPDLOCK,HOLDLOCK)
                   WHERE CodigoCuenta='199025')
        INSERT Contabilidad.CuentasContables
            (CodigoCuenta,NombreCuenta,IdCuentaSuperior,Naturaleza,Estado,
             EsImputable,EsCuentaValuacion,EsCatalogoRegulador)
        SELECT '199025','Faltantes de caja',IdCuentaContable,Naturaleza,1,0,0,1
        FROM Contabilidad.CuentasContables WHERE IdCuentaContable=@Mayor;

    SELECT @Subcuenta=IdCuentaContable FROM Contabilidad.CuentasContables WITH (UPDLOCK,HOLDLOCK)
    WHERE CodigoCuenta='199025' AND IdCuentaSuperior=@Mayor AND Estado=1
      AND Naturaleza='DEUDORA' AND EsCuentaValuacion=0;
    IF @Subcuenta IS NULL
        THROW 56331,N'La subcuenta 199025 requiere revisar su jerarquía o reclasificación.',1;

    IF EXISTS (SELECT 1 FROM Contabilidad.CuentasContables WHERE IdCuentaContable=@Subcuenta AND EsImputable=1)
    BEGIN
        DECLARE @EnPlantilla bit=0;
        IF OBJECT_ID('Contabilidad.PlantillaAsientoDetalle','U') IS NOT NULL
            EXEC sys.sp_executesql N'
                SELECT @EnUso=1 FROM Contabilidad.PlantillaAsientoDetalle WITH (HOLDLOCK)
                WHERE IdCuentaContable=@Id;',
                N'@Id int,@EnUso bit OUTPUT',@Subcuenta,@EnPlantilla OUTPUT;
        IF @EnPlantilla=1 OR EXISTS (SELECT 1 FROM Contabilidad.CuentasContables
                                   WHERE IdCuentaContable=@Subcuenta AND Saldo<>0)
           OR EXISTS (SELECT 1 FROM Contabilidad.MovimientosContables WITH (HOLDLOCK)
                      WHERE IdCuentaContable=@Subcuenta)
            THROW 56333,N'La subcuenta imputable tiene saldo, historia o plantillas. Requiere revisión.',1;
        UPDATE Contabilidad.CuentasContables SET EsImputable=0 WHERE IdCuentaContable=@Subcuenta;
    END;
    UPDATE Contabilidad.CuentasContables SET EsCatalogoRegulador=1
    WHERE IdCuentaContable=@Subcuenta AND EsCatalogoRegulador=0;

    IF NOT EXISTS (SELECT 1 FROM Contabilidad.CuentasContables WITH (UPDLOCK,HOLDLOCK)
                   WHERE CodigoCuenta='19902505')
        INSERT Contabilidad.CuentasContables
            (CodigoCuenta,NombreCuenta,IdCuentaSuperior,Naturaleza,Estado,
             EsImputable,EsCuentaValuacion,EsCatalogoRegulador)
        VALUES ('19902505','Faltantes de caja',@Subcuenta,'DEUDORA',1,1,0,0);

    IF NOT EXISTS (SELECT 1 FROM Contabilidad.CuentasContables WHERE CodigoCuenta='19902505'
                   AND IdCuentaSuperior=@Subcuenta AND Estado=1 AND EsImputable=1
                   AND Naturaleza='DEUDORA' AND EsCuentaValuacion=0 AND EsCatalogoRegulador=0
                   AND SoloAutomatica=0)
        THROW 56332,N'El auxiliar 19902505 difiere de la configuración verificada.',1;
    COMMIT;
END TRY
BEGIN CATCH
    IF XACT_STATE()<>0 ROLLBACK;
    THROW;
END CATCH;
