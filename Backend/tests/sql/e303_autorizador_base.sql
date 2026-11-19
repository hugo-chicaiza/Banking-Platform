CREATE   PROCEDURE Transacciones.usp_AutorizarOperacion
    @IdCuenta int, @IdCanal int, @TipoTransaccion varchar(30), @Monto decimal(18,2),
    @FechaHora datetime2 = NULL,
    @CodigoRespuesta char(2) OUTPUT, @Mensaje nvarchar(300) OUTPUT, @Comision decimal(18,2) = NULL OUTPUT
AS
/* Decide si una operación se puede registrar, antes de registrarla. Devuelve el código de respuesta:
     00 aprobada; 05 no aprobar (cuenta no activa o restricción del subproducto);
     51 fondos insuficientes; 61 excede el límite de monto; 65 excede el límite de frecuencia.
   Aplica: CU-03 (estado de la cuenta), PC-02 (cupo vigente con fn_CupoVigente),
   restricciones de ProductoRestriccion y comisiones de fn_CalcularComision (TR-04). */
BEGIN
    SET NOCOUNT ON;
    DECLARE @Estado varchar(10), @Saldo decimal(18,2), @Retenido decimal(18,2), @IdSub int, @Apertura datetime2, @Naturaleza char(1);
    DECLARE @CupoDia decimal(18,2), @CupoMes decimal(18,2), @MaxTx decimal(18,2), @MaxCant smallint;
    DECLARE @UsadoDia decimal(18,2), @UsadoMes decimal(18,2), @CantDia int, @Dia date, @Restriccion nvarchar(250);
    SET @FechaHora = ISNULL(@FechaHora, CAST(SYSDATETIMEOFFSET() AT TIME ZONE 'SA Pacific Standard Time' AS datetime2));
    SET @Dia = CAST(@FechaHora AS date);
    SET @CodigoRespuesta = '00'; SET @Mensaje = N'Aprobada';

    SELECT @Naturaleza = Naturaleza FROM Transacciones.TipoTransaccion WHERE CodigoTipo = @TipoTransaccion AND Estado = 'A';
    SELECT @Estado = Estado, @Saldo = Saldo, @Retenido = SaldoRetenido, @IdSub = IdSubProducto, @Apertura = FechaApertura
    FROM Cuentas.Cuenta WHERE IdCuenta = @IdCuenta;
    IF @Estado IS NULL BEGIN SET @CodigoRespuesta = '14'; SET @Mensaje = N'La cuenta no existe.'; RETURN; END;

    SELECT @Comision = ISNULL(SUM(MontoComision), 0) FROM Transacciones.fn_CalcularComision(@TipoTransaccion, @IdCanal, @Monto, @Dia);

    IF @Naturaleza = 'D' OR @Comision > 0
    BEGIN
        IF @Estado <> 'Activa' BEGIN SET @CodigoRespuesta = '05'; SET @Mensaje = N'La cuenta no está activa.'; RETURN; END;
        SELECT TOP (1) @Restriccion = r.Descripcion FROM ProductosFinancieros.ProductoRestriccion r
        WHERE r.IdSubProducto = @IdSub AND r.Estado = 'A' AND r.VigenciaDesde <= @Dia AND (r.VigenciaHasta IS NULL OR r.VigenciaHasta > @Dia)
          AND (   (r.TipoRestriccion = 'SIN_RETIROS'  AND @Naturaleza = 'D' AND DATEDIFF(day, @Apertura, @FechaHora) < r.Dias)
               OR (r.TipoRestriccion = 'SALDO_MINIMO' AND @Saldo - ISNULL(CASE WHEN @Naturaleza = 'D' THEN @Monto END, 0) - @Comision < r.Monto));
        IF @Restriccion IS NOT NULL BEGIN SET @CodigoRespuesta = '05'; SET @Mensaje = CONCAT(N'Restricción del producto: ', @Restriccion); RETURN; END;
        IF @Saldo - @Retenido < ISNULL(CASE WHEN @Naturaleza = 'D' THEN @Monto END, 0) + @Comision
        BEGIN SET @CodigoRespuesta = '51'; SET @Mensaje = N'Fondos insuficientes.'; RETURN; END;
    END;

    IF @Naturaleza = 'D'
    BEGIN
        SELECT @CupoDia = CupoDiario, @CupoMes = CupoMensual, @MaxTx = MontoMaxTransaccion, @MaxCant = MaxTransaccionesDia
        FROM Canal.fn_CupoVigente(@IdCuenta, @IdCanal);
        IF @CupoDia IS NOT NULL
        BEGIN
            SELECT @UsadoDia = ISNULL(SUM(CASE WHEN CAST(t.FechaHoraSistema AS date) = @Dia THEN t.Monto END), 0),
                   @CantDia  = ISNULL(SUM(CASE WHEN CAST(t.FechaHoraSistema AS date) = @Dia THEN 1 END), 0),
                   @UsadoMes = ISNULL(SUM(t.Monto), 0)
            FROM Transacciones.Transaccion t JOIN Transacciones.TipoTransaccion tt ON tt.CodigoTipo = t.TipoTransaccion
            WHERE t.IdCuenta = @IdCuenta AND t.IdCanal = @IdCanal AND t.Estado = 'Completada' AND t.TipoOperacion = 'Normal'
              AND tt.Naturaleza = 'D' AND t.FechaHoraSistema >= DATEFROMPARTS(YEAR(@Dia), MONTH(@Dia), 1) AND t.FechaHoraSistema < DATEADD(day, 1, @Dia);
            IF @Monto > @MaxTx OR @UsadoDia + @Monto > @CupoDia OR @UsadoMes + @Monto > @CupoMes
            BEGIN SET @CodigoRespuesta = '61'; SET @Mensaje = N'Excede el límite de monto.'; RETURN; END;
            IF @CantDia + 1 > @MaxCant
            BEGIN SET @CodigoRespuesta = '65'; SET @Mensaje = N'Excede el límite de frecuencia.'; RETURN; END;
        END;
    END;
END;