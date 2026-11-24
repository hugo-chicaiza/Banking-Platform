SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57631, 'Falta confirmar la base destino de la apertura de cuentas.', 1;

DECLARE @ChequeoCierre nvarchar(max) = OBJECT_DEFINITION(OBJECT_ID(N'Cuentas.CK_Cuenta_Cierre'));
IF @ChequeoCierre IS NULL
    THROW 57631, 'No se encontró la restricción de cierre que debe conservarse.', 1;
ALTER TABLE Cuentas.Cuenta DROP CONSTRAINT CK_Cuenta_Estado, CK_Cuenta_Cierre;
ALTER TABLE Cuentas.Cuenta ALTER COLUMN Estado varchar(18) NOT NULL;
ALTER TABLE Cuentas.Cuenta WITH CHECK ADD CONSTRAINT CK_Cuenta_Estado
    CHECK (Estado IN ('PendienteDeposito', 'Activa', 'Inactiva', 'Bloqueada', 'Cerrada', 'Anulada'));
DECLARE @RestaurarCierre nvarchar(max) =
    N'ALTER TABLE Cuentas.Cuenta WITH CHECK ADD CONSTRAINT CK_Cuenta_Cierre CHECK ' + @ChequeoCierre;
EXEC sys.sp_executesql @RestaurarCierre;

ALTER TABLE Cuentas.Cuenta ADD MontoAperturaAplicado decimal(18,2) NULL,
    FechaActivacion datetime2 NULL;

CREATE TABLE Cuentas.CuentaEvento (
    IdCuentaEvento bigint IDENTITY PRIMARY KEY,
    IdCuenta int NOT NULL REFERENCES Cuentas.Cuenta (IdCuenta),
    TipoEvento varchar(20) NOT NULL,
    EstadoAnterior varchar(18) NULL,
    EstadoActual varchar(18) NOT NULL,
    RealizadoPor int NOT NULL,
    IdAgencia char(3) NOT NULL,
    FechaEvento datetime2 NOT NULL CONSTRAINT DF_CuentaEvento_Fecha DEFAULT (SYSUTCDATETIME())
);
CREATE INDEX IX_CuentaEvento_Cuenta ON Cuentas.CuentaEvento (IdCuenta, IdCuentaEvento);
GO

CREATE OR ALTER TRIGGER Cuentas.trg_CuentaEvento_Inmutable ON Cuentas.CuentaEvento AFTER UPDATE, DELETE
AS
BEGIN
    SET NOCOUNT ON;
    THROW 57633, 'El historial de apertura y activación es inmutable.', 1;
END;
GO

UPDATE Cuentas.Cuenta
SET FechaActivacion = CONVERT(datetime2, FechaApertura AT TIME ZONE 'SA Pacific Standard Time' AT TIME ZONE 'UTC')
WHERE Estado IN ('Activa', 'Inactiva', 'Bloqueada', 'Cerrada');

ALTER TABLE Cuentas.Cuenta WITH CHECK ADD CONSTRAINT CK_Cuenta_PrimerDeposito CHECK (
    (MontoAperturaAplicado IS NULL OR MontoAperturaAplicado >= 0)
    AND (Estado <> 'PendienteDeposito' OR (
        Saldo = 0 AND SaldoRetenido = 0 AND MontoAperturaAplicado IS NOT NULL AND FechaActivacion IS NULL
    ))
);

INSERT Cuentas.CuentaEvento (IdCuenta, TipoEvento, EstadoActual, RealizadoPor, IdAgencia, FechaEvento)
SELECT IdCuenta, 'Apertura', 'Activa', CreadoPor, IdAgencia, FechaActivacion
FROM Cuentas.Cuenta WHERE FechaActivacion IS NOT NULL;

INSERT Parametros.Parametro (Clave, Modulo, Descripcion, TipoDato, Unidad, ValorMinimo, ValorMaximo, EsSensible)
SELECT v.Clave, 'Clientes', v.Descripcion, v.Tipo, v.Unidad, v.Minimo, v.Maximo, 1
FROM (VALUES
    ('CLI_RIESGO_VIGENCIA_ALTO_MESES', N'Vigencia de riesgo alto', 'Entero', 'meses', 1, 120),
    ('CLI_RIESGO_VIGENCIA_MEDIO_MESES', N'Vigencia de riesgo medio', 'Entero', 'meses', 1, 120),
    ('CLI_RIESGO_VIGENCIA_BAJO_MESES', N'Vigencia de riesgo bajo', 'Entero', 'meses', 1, 120),
    ('CLI_EXIGE_ARCHIVOS', N'Exigir archivos obligatorios para contratar', 'Booleano', NULL, NULL, NULL)
) v(Clave, Descripcion, Tipo, Unidad, Minimo, Maximo)
WHERE NOT EXISTS (SELECT 1 FROM Parametros.Parametro p WHERE p.Clave = v.Clave);

INSERT Parametros.ParametroValor (IdParametro, Valor, VigenciaDesde, CreadoPor)
SELECT p.IdParametro, v.Valor, '19000101', NULL
FROM (VALUES ('CLI_RIESGO_VIGENCIA_ALTO_MESES', '12'), ('CLI_RIESGO_VIGENCIA_MEDIO_MESES', '24'),
             ('CLI_RIESGO_VIGENCIA_BAJO_MESES', '36'), ('CLI_EXIGE_ARCHIVOS', 'false')) v(Clave, Valor)
JOIN Parametros.Parametro p ON p.Clave = v.Clave
WHERE NOT EXISTS (
    SELECT 1 FROM Parametros.ParametroValor pv WHERE pv.IdParametro = p.IdParametro AND pv.IdAgencia IS NULL
);
GO

CREATE OR ALTER PROCEDURE Cuentas.usp_AbrirCuenta
    @IdCliente int, @IdSubProducto int, @IdAgencia char(3), @NumeroCuenta varchar(20),
    @MontoAperturaAplicado decimal(18,2), @CreadoPor int, @IdCuenta int OUTPUT
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;
    IF @@TRANCOUNT = 0 THROW 57632, 'La apertura requiere una transacción.', 1;

    INSERT Cuentas.Cuenta (NumeroCuenta, IdCliente, IdSubProducto, IdProducto, IdAgencia,
                            Saldo, SaldoRetenido, Estado, CreadoPor, MontoAperturaAplicado)
    SELECT @NumeroCuenta, @IdCliente, s.IdSubProducto, s.IdProducto, @IdAgencia,
           0, 0, 'PendienteDeposito', @CreadoPor, @MontoAperturaAplicado
    FROM ProductosFinancieros.SubProducto s
    JOIN ProductosFinancieros.Producto p ON p.IdProducto = s.IdProducto
    WHERE s.IdSubProducto = @IdSubProducto AND p.TipoProducto = 'Cuenta'
      AND p.Estado = 'A' AND p.EstadoProducto = 'Activo' AND s.Estado = 'A' AND s.EstadoSubProducto = 'Activo';
    IF @@ROWCOUNT <> 1 THROW 52104, 'El subproducto de cuenta no está activo.', 1;

    SET @IdCuenta = CONVERT(int, SCOPE_IDENTITY());
    INSERT Cuentas.CuentaEvento (IdCuenta, TipoEvento, EstadoActual, RealizadoPor, IdAgencia)
    VALUES (@IdCuenta, 'Apertura', 'PendienteDeposito', @CreadoPor, @IdAgencia);
END;
