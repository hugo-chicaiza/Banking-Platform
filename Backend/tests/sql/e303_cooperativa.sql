-- Esquema representativo real, sin filas de clientes; solo laboratorio SQL local propio.

IF SCHEMA_ID(N'Canal') IS NULL EXEC(N'CREATE SCHEMA [Canal]');

IF SCHEMA_ID(N'Catalogo') IS NULL EXEC(N'CREATE SCHEMA [Catalogo]');

IF SCHEMA_ID(N'Clientes') IS NULL EXEC(N'CREATE SCHEMA [Clientes]');

IF SCHEMA_ID(N'Contabilidad') IS NULL EXEC(N'CREATE SCHEMA [Contabilidad]');

IF SCHEMA_ID(N'Credito') IS NULL EXEC(N'CREATE SCHEMA [Credito]');

IF SCHEMA_ID(N'Cuentas') IS NULL EXEC(N'CREATE SCHEMA [Cuentas]');

IF SCHEMA_ID(N'Organizacion') IS NULL EXEC(N'CREATE SCHEMA [Organizacion]');

IF SCHEMA_ID(N'ProductosFinancieros') IS NULL EXEC(N'CREATE SCHEMA [ProductosFinancieros]');

IF SCHEMA_ID(N'Tarjeta') IS NULL EXEC(N'CREATE SCHEMA [Tarjeta]');

IF SCHEMA_ID(N'Transacciones') IS NULL EXEC(N'CREATE SCHEMA [Transacciones]');

CREATE SEQUENCE [Organizacion].[SeqAgenciaId] AS int START WITH 1 INCREMENT BY 1;

CREATE TABLE Canal.Canal (
 [IdCanal] int IDENTITY(1,1) NOT NULL,
 [CodigoCanal] varchar(10) NOT NULL,
 [NombreCanal] varchar(50) NOT NULL,
 [Descripcion] varchar(200) NOT NULL,
 [RequiereTarjeta] bit NOT NULL DEFAULT ((0)),
 [RequierePin] bit NOT NULL DEFAULT ((0)),
 [RequiereTerminal] bit NOT NULL DEFAULT ((0)),
 [ModoDigitalPresencial] varchar(12) NULL,
 [RequiereJornadaCaja] bit NOT NULL DEFAULT ((0)),
 [Estado] char(1) NOT NULL DEFAULT (('A') collate SQL_Latin1_General_CP1_CI_AS),
 [FechaCreacion] datetime2(7) NOT NULL DEFAULT (CONVERT([datetime2],(sysdatetimeoffset() AT TIME ZONE 'SA Pacific Standard Time')))
);

CREATE TABLE Canal.CanalCupoClienteCustom (
 [IdCanalCupo] int IDENTITY(1,1) NOT NULL,
 [IdCuenta] int NOT NULL,
 [IdCanal] int NOT NULL,
 [CupoDiario] decimal(18,2) NOT NULL,
 [CupoMensual] decimal(18,2) NOT NULL,
 [MontoMaxTransaccion] decimal(18,2) NOT NULL,
 [MaxTransaccionesDia] smallint NOT NULL,
 [FechaVigencia] date NULL,
 [Estado] char(1) NOT NULL DEFAULT (('A') collate SQL_Latin1_General_CP1_CI_AS),
 [FechaRegistro] datetime2(7) NOT NULL DEFAULT (CONVERT([datetime2],(sysdatetimeoffset() AT TIME ZONE 'SA Pacific Standard Time'))),
 [ModificadoPor] int NOT NULL
);

CREATE TABLE Canal.CuposModHis (
 [IdCupoModHis] bigint IDENTITY(1,1) NOT NULL,
 [IdCanalCupoCliente] int NOT NULL,
 [CupoDiarioAnterior] decimal(18,2) NULL,
 [CupoDiarioNuevo] decimal(18,2) NULL,
 [CupoMensualAnterior] decimal(18,2) NULL,
 [CupoMensualNuevo] decimal(18,2) NULL,
 [MontoMaxTxAnterior] decimal(18,2) NULL,
 [MontoMaxTxNuevo] decimal(18,2) NULL,
 [ModificadoPor] int NOT NULL,
 [FechaModificacion] datetime2(7) NOT NULL DEFAULT (CONVERT([datetime2],(sysdatetimeoffset() AT TIME ZONE 'SA Pacific Standard Time')))
);

CREATE TABLE Catalogo.Ciudad (
 [IdCiudad] int IDENTITY(1,1) NOT NULL,
 [CodigoPais] char(3) NOT NULL,
 [Nombre] varchar(80) NOT NULL,
 [Provincia] varchar(80) NOT NULL,
 [FechaRegistro] datetime2(7) NOT NULL DEFAULT (CONVERT([datetime2],(sysdatetimeoffset() AT TIME ZONE 'SA Pacific Standard Time'))),
 [Estado] char(1) NOT NULL DEFAULT ('A')
);

CREATE TABLE Catalogo.SistemaAmortizacion (
 [Codigo] varchar(10) NOT NULL,
 [Nombre] varchar(60) NOT NULL,
 [Descripcion] varchar(250) NOT NULL,
 [Estado] char(1) NOT NULL DEFAULT ('A')
);

CREATE TABLE Clientes.Cliente (
 [IdCliente] int IDENTITY(1,1) NOT NULL,
 [Identificacion] varchar(13) NOT NULL,
 [TipoDocumento] varchar(10) NOT NULL,
 [TipoCliente] varchar(10) NOT NULL,
 [RazonSocial] varchar(250) NULL,
 [NombreComercial] varchar(250) NULL,
 [IdActividadEconomica] int NULL,
 [Nombres] varchar(250) NOT NULL,
 [Apellidos] varchar(250) NULL,
 [FechaNacimiento] date NOT NULL,
 [Genero] char(1) NULL,
 [CodigoPaisNacionalidad] char(3) NOT NULL DEFAULT (('ECU') collate SQL_Latin1_General_CP1_CI_AS),
 [EstadoCivil] varchar(20) NULL,
 [TelefonoConvencional] varchar(15) NULL,
 [TelefonoCelular] varchar(15) NOT NULL,
 [Email] varchar(150) NOT NULL,
 [ConsentimientoDatos] bit NOT NULL,
 [FechaConsentimiento] datetime2(7) NOT NULL,
 [Estado] varchar(10) NOT NULL DEFAULT ('Pendiente'),
 [FechaRegistro] datetime2(7) NOT NULL DEFAULT (CONVERT([datetime2],(sysdatetimeoffset() AT TIME ZONE 'SA Pacific Standard Time'))),
 [CreadoPor] int NOT NULL
);

CREATE TABLE Clientes.RiesgoCliente (
 [IdEvaluacion] int IDENTITY(1,1) NOT NULL,
 [IdCliente] int NOT NULL,
 [NivelRiesgoLAFT] varchar(10) NOT NULL,
 [EsPEP] bit NOT NULL DEFAULT ((0)),
 [ResultadoEvaluacion] varchar(10) NOT NULL,
 [FechaEvaluacion] datetime2(7) NOT NULL DEFAULT (CONVERT([datetime2],(sysdatetimeoffset() AT TIME ZONE 'SA Pacific Standard Time'))),
 [Evaluador] int NOT NULL,
 [Observaciones] varchar(250) NULL,
 [TieneAntecedentes] bit NOT NULL DEFAULT ((0)),
 [IdTipoAntecedente] int NULL,
 [EsVigente] bit NOT NULL DEFAULT ((0))
);

CREATE TABLE Contabilidad.FechaContable (
 [IdFechaContable] int IDENTITY(1,1) NOT NULL,
 [Fecha] date NOT NULL,
 [Anio] AS (datepart(year,[Fecha])),
 [Mes] AS (datepart(month,[Fecha])),
 [Dia] AS (datepart(day,[Fecha])),
 [NumeroDiaSemana] tinyint NOT NULL,
 [NombreDiaSemana] varchar(15) NOT NULL,
 [EsFeriado] bit NOT NULL DEFAULT ((0)),
 [IdFeriado] int NULL,
 [FechaRegistro] datetime2(7) NOT NULL DEFAULT (CONVERT([datetime2],(sysdatetimeoffset() AT TIME ZONE 'SA Pacific Standard Time'))),
 [HoraCorte] time(0) NOT NULL DEFAULT ('19:00:00'),
 [EsFinDeSemana] AS (CONVERT([bit],case when [NumeroDiaSemana]=(7) OR [NumeroDiaSemana]=(6) then (1) else (0) end)),
 [EsDiaContable] AS (CONVERT([bit],case when NOT ([NumeroDiaSemana]=(7) OR [NumeroDiaSemana]=(6)) AND [EsFeriado]=(0) then (1) else (0) end))
);

CREATE TABLE Credito.CreditoDesembolso (
 [IdDesembolso] bigint IDENTITY(1,1) NOT NULL,
 [NumeroDesembolso] varchar(30) NOT NULL,
 [IdCliente] int NOT NULL,
 [IdTipoCredito] int NOT NULL,
 [IdCuentaDesembolso] int NOT NULL,
 [IdAgencia] char(3) NOT NULL,
 [MontoDesembolsado] decimal(18,2) NOT NULL,
 [TasaNominalAnual] decimal(6,4) NOT NULL,
 [Estado] varchar(15) NOT NULL DEFAULT ('PENDIENTE'),
 [FechaDesembolso] datetime2(7) NULL,
 [FechaResolucion] datetime2(7) NULL,
 [FechaHoraSistema] datetime2(7) NOT NULL DEFAULT (CONVERT([datetime2],(sysdatetimeoffset() AT TIME ZONE 'SA Pacific Standard Time'))),
 [AprobadoPor] int NULL,
 [DesembolsadoPor] int NULL,
 [IdTransaccionDesembolso] bigint NULL,
 [IdSolicitud] bigint NOT NULL
);

CREATE TABLE Credito.CreditoSolicitud (
 [IdSolicitud] bigint IDENTITY(1,1) NOT NULL,
 [NumeroSolicitud] varchar(20) NOT NULL,
 [IdCliente] int NOT NULL,
 [IdTipoCredito] int NOT NULL,
 [IdProducto] int NOT NULL,
 [IdAgencia] char(3) NOT NULL,
 [IdCanal] int NOT NULL,
 [IdSituacion] bigint NOT NULL,
 [IdReporteBuro] bigint NULL,
 [Monto] decimal(18,2) NOT NULL,
 [PlazoMeses] smallint NOT NULL,
 [SistemaAmortizacion] varchar(10) NOT NULL,
 [TasaNominalAnual] decimal(6,4) NOT NULL,
 [CuotaReferencial] decimal(18,2) NOT NULL,
 [TotalIntereses] decimal(18,2) NOT NULL,
 [TotalSeguros] decimal(18,2) NOT NULL,
 [TotalImpuestos] decimal(18,2) NOT NULL DEFAULT ((0)),
 [CapacidadPago] decimal(18,2) NOT NULL,
 [Estado] varchar(20) NOT NULL,
 [ConsienteConsultaBuro] bit NOT NULL DEFAULT ((0)),
 [DeclaraLicitudFondos] bit NOT NULL DEFAULT ((0)),
 [FechaSolicitud] date NOT NULL,
 [FechaResolucion] datetime2(7) NULL,
 [FechaHoraSistema] datetime2(7) NOT NULL DEFAULT (CONVERT([datetime2],(sysdatetimeoffset() AT TIME ZONE 'SA Pacific Standard Time'))),
 [TipoRevision] varchar(15) NULL,
 [AprobadoPor] int NULL,
 [CreadoPor] int NOT NULL,
 [Observaciones] varchar(500) NULL,
 [IdGarante] int NULL,
 [IdFechaContable] int NOT NULL,
 [IdSubProducto] int NULL
);

CREATE TABLE Credito.Seguro (
 [IdSeguro] int IDENTITY(1,1) NOT NULL,
 [CodigoSeguro] varchar(15) NOT NULL,
 [Nombre] varchar(60) NOT NULL,
 [Aseguradora] varchar(100) NULL,
 [TipoCalculo] varchar(10) NOT NULL,
 [Valor] decimal(12,6) NOT NULL,
 [Estado] char(1) NOT NULL DEFAULT (('A') collate SQL_Latin1_General_CP1_CI_AS),
 [VigenciaDesde] date NOT NULL,
 [VigenciaHasta] date NULL
);

CREATE TABLE Credito.TasaInteres (
 [IdTasaInteres] int IDENTITY(1,1) NOT NULL,
 [IdTipoCredito] int NULL,
 [PlazoMaximoMeses] smallint NULL,
 [TasaNominalAnual] decimal(6,4) NOT NULL,
 [RecargoMoraSobreTasa] decimal(6,4) NOT NULL DEFAULT ((0)),
 [MontoMinimo] decimal(18,2) NULL,
 [MontoMaximo] decimal(18,2) NULL,
 [VigenciaDesde] date NOT NULL,
 [VigenciaHasta] date NULL,
 [Estado] char(1) NOT NULL DEFAULT ('A'),
 [TipoTasa] varchar(20) NOT NULL DEFAULT ('CREDITO')
);

CREATE TABLE Credito.TipoCredito (
 [IdTipoCredito] int IDENTITY(1,1) NOT NULL,
 [CodigoTipoCredito] varchar(15) NOT NULL,
 [Nombre] varchar(60) NOT NULL,
 [Descripcion] varchar(250) NULL,
 [Estado] char(1) NOT NULL DEFAULT (('A') collate SQL_Latin1_General_CP1_CI_AS),
 [FechaRegistro] datetime2(7) NOT NULL DEFAULT (CONVERT([datetime2],(sysdatetimeoffset() AT TIME ZONE 'SA Pacific Standard Time')))
);

CREATE TABLE Cuentas.Cuenta (
 [IdCuenta] int IDENTITY(1,1) NOT NULL,
 [NumeroCuenta] varchar(20) NOT NULL,
 [IdCliente] int NOT NULL,
 [IdAgencia] char(3) NOT NULL,
 [IdProducto] int NOT NULL,
 [Saldo] decimal(18,2) NOT NULL DEFAULT ((0)),
 [SaldoRetenido] decimal(18,2) NOT NULL DEFAULT ((0)),
 [Estado] varchar(10) NOT NULL DEFAULT (('Activa') collate SQL_Latin1_General_CP1_CI_AS),
 [FechaApertura] datetime2(7) NOT NULL DEFAULT (CONVERT([datetime2],(sysdatetimeoffset() AT TIME ZONE 'SA Pacific Standard Time'))),
 [FechaUltimoMovimiento] datetime2(7) NULL,
 [FechaCierre] datetime2(7) NULL,
 [CreadoPor] int NOT NULL,
 [IdSubProducto] int NOT NULL
);

CREATE TABLE Cuentas.MovimientoTransaccion (
 [IdMovimiento] bigint IDENTITY(1,1) NOT NULL,
 [IdTransaccion] bigint NOT NULL,
 [IdCuenta] int NOT NULL,
 [TipoMovimiento] char(1) NOT NULL,
 [RolCuenta] varchar(7) NULL,
 [Monto] decimal(18,2) NOT NULL,
 [SaldoAnterior] decimal(18,2) NOT NULL,
 [SaldoPosterior] decimal(18,2) NOT NULL,
 [FechaHoraSistema] datetime2(7) NOT NULL DEFAULT (CONVERT([datetime2],(sysdatetimeoffset() AT TIME ZONE 'SA Pacific Standard Time'))),
 [IdFechaContable] int NOT NULL
);

CREATE TABLE Organizacion.Agencia (
 [IdAgencia] char(3) NOT NULL DEFAULT (right('000'+CONVERT([varchar](10),NEXT VALUE FOR [Organizacion].[SeqAgenciaId]),(3))),
 [Codigo] varchar(10) NOT NULL,
 [TipoAgencia] varchar(10) NOT NULL,
 [Estado] char(1) NOT NULL DEFAULT (('A') collate SQL_Latin1_General_CP1_CI_AS),
 [Telefono] varchar(15) NULL,
 [Direccion] varchar(250) NULL,
 [FechaCreacion] datetime2(7) NOT NULL DEFAULT (CONVERT([datetime2],(sysdatetimeoffset() AT TIME ZONE 'SA Pacific Standard Time'))),
 [IdCiudad] int NOT NULL,
 [KeyAgencia] varchar(64) NULL,
 [IdEntidad] tinyint NOT NULL DEFAULT ((1)),
 [VersionFila] rowversion NOT NULL
);

CREATE TABLE ProductosFinancieros.Producto (
 [IdProducto] int IDENTITY(1,1) NOT NULL,
 [CodigoProducto] varchar(10) NOT NULL,
 [NombreProducto] varchar(100) NOT NULL,
 [TipoProducto] varchar(10) NOT NULL,
 [MontoAperturaMinimo] decimal(18,2) NOT NULL DEFAULT ((0)),
 [IdTipoCredito] int NULL,
 [PermiteOperacionesPresenciales] bit NOT NULL DEFAULT ((1)),
 [Estado] char(1) NOT NULL DEFAULT (('A') collate SQL_Latin1_General_CP1_CI_AS),
 [IdRed] int NULL,
 [TipoCuenta] varchar(20) NULL,
 [Descripcion] varchar(250) NULL,
 [IdTipoProducto] int NULL,
 [Moneda] char(3) NOT NULL DEFAULT ('USD'),
 [EstadoProducto] varchar(12) NULL,
 [ModificadoPor] int NULL,
 [FechaModificacion] datetime2(7) NULL
);

CREATE TABLE ProductosFinancieros.ProductoCanalCupo (
 [IdProductoCanalCupo] int IDENTITY(1,1) NOT NULL,
 [IdCanal] int NOT NULL,
 [CupoDiarioMaximo] decimal(18,2) NOT NULL,
 [CupoMensualMaximo] decimal(18,2) NOT NULL,
 [MontoMaxTransaccion] decimal(18,2) NOT NULL,
 [MaxTransaccionesDia] smallint NOT NULL,
 [FechaRegistro] datetime2(7) NOT NULL DEFAULT (CONVERT([datetime2],(sysdatetimeoffset() AT TIME ZONE 'SA Pacific Standard Time'))),
 [IdSubProducto] int NOT NULL,
 [VigenciaDesde] date NOT NULL DEFAULT (CONVERT([date],'20260101',(112))),
 [VigenciaHasta] date NULL,
 [EstadoCupo] char(1) NOT NULL DEFAULT ('A'),
 [IdSolicitud] bigint NULL
);

CREATE TABLE ProductosFinancieros.ProductoComision (
 [IdVinculo] int IDENTITY(1,1) NOT NULL,
 [IdComision] int NOT NULL,
 [IdProducto] int NULL,
 [IdSubProducto] int NULL,
 [Exonerado] bit NOT NULL DEFAULT ((0)),
 [Estado] char(1) NOT NULL DEFAULT ('A'),
 [AsignadoPor] int NOT NULL,
 [FechaAsignacion] datetime2(7) NOT NULL DEFAULT (sysutcdatetime())
);

CREATE TABLE ProductosFinancieros.ProductoRestriccion (
 [IdRestriccion] int IDENTITY(1,1) NOT NULL,
 [IdSubProducto] int NOT NULL,
 [TipoRestriccion] varchar(20) NOT NULL,
 [Dias] smallint NULL,
 [Monto] decimal(18,2) NULL,
 [Descripcion] varchar(250) NOT NULL,
 [VigenciaDesde] date NOT NULL,
 [VigenciaHasta] date NULL,
 [Estado] char(1) NOT NULL DEFAULT ('A'),
 [RegistradoPor] int NOT NULL
);

CREATE TABLE ProductosFinancieros.ProductoSeguro (
 [IdVinculo] int IDENTITY(1,1) NOT NULL,
 [IdSeguro] int NOT NULL,
 [IdProducto] int NULL,
 [IdSubProducto] int NULL,
 [EsObligatorio] bit NOT NULL DEFAULT ((0)),
 [Estado] char(1) NOT NULL DEFAULT ('A'),
 [AsignadoPor] int NOT NULL,
 [FechaAsignacion] datetime2(7) NOT NULL DEFAULT (sysutcdatetime())
);

CREATE TABLE ProductosFinancieros.ProductoSistemaAmortizacion (
 [IdVinculo] int IDENTITY(1,1) NOT NULL,
 [CodigoSistema] varchar(10) NOT NULL,
 [IdProducto] int NULL,
 [IdSubProducto] int NULL,
 [Estado] char(1) NOT NULL DEFAULT ('A'),
 [AsignadoPor] int NOT NULL,
 [FechaAsignacion] datetime2(7) NOT NULL DEFAULT (sysutcdatetime())
);

CREATE TABLE ProductosFinancieros.ProductoTasaInteres (
 [IdVinculo] int IDENTITY(1,1) NOT NULL,
 [IdTasaInteres] int NOT NULL,
 [IdProducto] int NULL,
 [IdSubProducto] int NULL,
 [Estado] char(1) NOT NULL DEFAULT ('A'),
 [AsignadoPor] int NOT NULL,
 [FechaAsignacion] datetime2(7) NOT NULL DEFAULT (sysutcdatetime())
);

CREATE TABLE ProductosFinancieros.Red (
 [IdRed] int IDENTITY(1,1) NOT NULL,
 [CodigoRed] varchar(20) NOT NULL,
 [Nombre] varchar(60) NOT NULL,
 [IngresoMinimo] decimal(18,2) NULL,
 [EdadMinima] tinyint NULL,
 [RequiereCuentaActiva] bit NOT NULL DEFAULT ((1)),
 [Descripcion] varchar(250) NULL,
 [Estado] char(1) NOT NULL DEFAULT ('A')
);

CREATE TABLE ProductosFinancieros.SubProducto (
 [IdSubProducto] int IDENTITY(1,1) NOT NULL,
 [IdProducto] int NOT NULL,
 [CodigoSubProducto] varchar(15) NOT NULL,
 [NombreSubProducto] varchar(100) NOT NULL,
 [Estado] char(1) NOT NULL DEFAULT (('A') collate SQL_Latin1_General_CP1_CI_AS),
 [FechaRegistro] datetime2(7) NOT NULL DEFAULT (CONVERT([datetime2],(sysdatetimeoffset() AT TIME ZONE 'SA Pacific Standard Time'))),
 [IdBIN] int NULL,
 [EdadMinima] tinyint NULL,
 [EdadMaxima] tinyint NULL,
 [EstadoSubProducto] varchar(12) NULL,
 [TipoClientePermitido] varchar(10) NOT NULL DEFAULT ('Ambos'),
 [RequiereTutor] bit NOT NULL DEFAULT ((0)),
 [IdSubProductoRequerido] int NULL,
 [MaximoPorCliente] smallint NULL,
 [ModificadoPor] int NULL,
 [FechaModificacion] datetime2(7) NULL
);

CREATE TABLE ProductosFinancieros.SubProductoCondicion (
 [IdCondicion] int IDENTITY(1,1) NOT NULL,
 [IdSubProducto] int NOT NULL,
 [MontoAperturaMinimo] decimal(18,2) NOT NULL,
 [SaldoMinimo] decimal(18,2) NOT NULL,
 [TasaInteresAnual] decimal(7,4) NOT NULL DEFAULT ((0)),
 [PeriodicidadInteres] varchar(12) NULL,
 [CostoMantenimiento] decimal(18,2) NOT NULL DEFAULT ((0)),
 [PeriodicidadCosto] varchar(12) NULL,
 [MesesInactividad] smallint NULL,
 [AplicaACuentasExistentes] bit NOT NULL DEFAULT ((0)),
 [VigenciaDesde] date NOT NULL,
 [VigenciaHasta] date NULL,
 [Estado] varchar(12) NOT NULL DEFAULT ('Pendiente'),
 [IdSolicitud] bigint NULL,
 [CreadoPor] int NULL,
 [FechaCreacion] datetime2(7) NOT NULL DEFAULT (sysutcdatetime())
);

CREATE TABLE ProductosFinancieros.TipoProducto (
 [IdTipoProducto] int NOT NULL,
 [Codigo] varchar(25) NOT NULL,
 [Nombre] varchar(60) NOT NULL,
 [SubcuentaCatalogo] varchar(6) NULL,
 [GeneraNumeroCuenta] bit NOT NULL,
 [Estado] char(1) NOT NULL DEFAULT ('A')
);

CREATE TABLE ProductosFinancieros.TipoRestriccion (
 [Codigo] varchar(30) NOT NULL,
 [Nombre] varchar(80) NOT NULL,
 [UsaDias] bit NOT NULL,
 [UsaMonto] bit NOT NULL,
 [UsaCantidad] bit NOT NULL
);

CREATE TABLE Tarjeta.Tarjeta (
 [IdTarjeta] int IDENTITY(1,1) NOT NULL,
 [TokenTarjeta] varchar(100) NOT NULL,
 [NumeroEnmascarado] char(19) NOT NULL,
 [HashNumeroTarjeta] varbinary(32) NOT NULL,
 [NombreTarjeta] varchar(26) NOT NULL,
 [TipoTarjeta] varchar(10) NOT NULL,
 [NombresTitular] varchar(250) NOT NULL,
 [ApellidosTitular] varchar(250) NOT NULL,
 [IdCliente] int NOT NULL,
 [IdCuenta] int NOT NULL,
 [IdProducto] int NOT NULL,
 [IdAgencia] char(3) NULL,
 [EsExtension] bit NOT NULL DEFAULT ((0)),
 [IdTarjetaTitular] int NULL,
 [FechaSolicitud] date NULL,
 [FechaResolucion] datetime2(7) NULL,
 [FechaEmision] date NOT NULL,
 [FechaExpiracion] date NOT NULL,
 [PinAsignado] bit NOT NULL DEFAULT ((0)),
 [FechaUltimoMovimiento] datetime2(7) NULL,
 [ValorUltimoMovimiento] decimal(18,2) NULL,
 [FechaRegistro] datetime2(7) NOT NULL DEFAULT (CONVERT([datetime2],(sysdatetimeoffset() AT TIME ZONE 'SA Pacific Standard Time'))),
 [CreadoPor] int NOT NULL,
 [IdBIN] int NULL,
 [IdSubProducto] int NOT NULL,
 [Estado] varchar(20) NOT NULL DEFAULT ('Solicitada')
);

CREATE TABLE Transacciones.Comisiones (
 [IdComision] int IDENTITY(1,1) NOT NULL,
 [CodigoComision] varchar(10) NOT NULL,
 [TipoComision] varchar(30) NOT NULL,
 [TipoCalculo] varchar(10) NOT NULL,
 [Valor] decimal(12,4) NOT NULL,
 [MontoMinimo] decimal(18,2) NULL,
 [MontoMaximo] decimal(18,2) NULL,
 [IdCanal] int NOT NULL,
 [Descripcion] varchar(250) NOT NULL,
 [VigenciaDesde] date NOT NULL,
 [VigenciaHasta] date NULL,
 [FechaRegistro] datetime2(7) NOT NULL DEFAULT (CONVERT([datetime2],(sysdatetimeoffset() AT TIME ZONE 'SA Pacific Standard Time'))),
 [Estado] char(1) NOT NULL DEFAULT (('A') collate SQL_Latin1_General_CP1_CI_AS),
 [IdCuentaContableIngreso] int NULL
);

CREATE TABLE Transacciones.TipoTransaccion (
 [CodigoTipo] varchar(30) NOT NULL,
 [Nombre] varchar(80) NOT NULL,
 [Naturaleza] char(1) NULL,
 [AfectaSaldo] bit NOT NULL,
 [Descripcion] varchar(250) NULL,
 [Estado] char(1) NOT NULL DEFAULT ('A')
);

CREATE TABLE Transacciones.Transaccion (
 [IdTransaccion] bigint IDENTITY(1,1) NOT NULL,
 [NumeroComprobante] varchar(30) NOT NULL,
 [Secuencial] char(6) NOT NULL,
 [RegistroUnico] char(12) NOT NULL,
 [NumeroAutorizacion] char(6) NULL,
 [MTI] char(4) NOT NULL DEFAULT (('0200') collate SQL_Latin1_General_CP1_CI_AS),
 [CodigoProcesamiento] char(6) NOT NULL,
 [STAN] char(6) NULL,
 [RRN] char(12) NULL,
 [TipoOperacion] varchar(10) NOT NULL DEFAULT (('Normal') collate SQL_Latin1_General_CP1_CI_AS),
 [TipoTransaccion] varchar(30) NOT NULL,
 [IdCuenta] int NOT NULL,
 [IdCuentaDestino] int NULL,
 [IdTarjeta] int NULL,
 [IdCanal] int NOT NULL,
 [IdATM] int NULL,
 [IdAgencia] char(3) NULL,
 [IdCiudad] int NULL,
 [IdJornadaCaja] int NULL,
 [IdTransaccionRelacionada] bigint NULL,
 [Monto] decimal(18,2) NOT NULL,
 [CodigoPaisOrigen] char(3) NOT NULL DEFAULT (('ECU') collate SQL_Latin1_General_CP1_CI_AS),
 [CodigoAdquirente] varchar(11) NULL,
 [CodigoRespuestaTerminal] char(2) NULL,
 [FechaHoraSistema] datetime2(7) NOT NULL DEFAULT (CONVERT([datetime2],(sysdatetimeoffset() AT TIME ZONE 'SA Pacific Standard Time'))),
 [FechaRegistro] datetime2(7) NOT NULL DEFAULT (CONVERT([datetime2],(sysdatetimeoffset() AT TIME ZONE 'SA Pacific Standard Time'))),
 [CodigoRespuesta] char(2) NOT NULL DEFAULT (('00') collate SQL_Latin1_General_CP1_CI_AS),
 [DireccionIP] varchar(45) NULL,
 [Estado] varchar(12) NOT NULL DEFAULT (('Completada') collate SQL_Latin1_General_CP1_CI_AS),
 [CreadoPor] int NOT NULL,
 [CodigoEmisor] varchar(11) NULL,
 [IdFechaContable] int NOT NULL,
 [FechaSistema] date NOT NULL DEFAULT (CONVERT([date],(sysdatetimeoffset() AT TIME ZONE 'SA Pacific Standard Time'))),
 [HoraSistema] time(7) NOT NULL DEFAULT (CONVERT([time],(sysdatetimeoffset() AT TIME ZONE 'SA Pacific Standard Time'))),
 [FechaDispositivo] date NOT NULL,
 [HoraDispositivo] time(7) NOT NULL
);

CREATE TABLE Transacciones.ComisionTipoTransaccion (
 [IdComisionTipoTransaccion] int IDENTITY(1,1) NOT NULL,
 [CodigoTipoTransaccion] varchar(30) NOT NULL,
 [IdCanal] int NOT NULL,
 [IdComision] int NOT NULL,
 [VigenciaDesde] date NOT NULL,
 [VigenciaHasta] date NULL,
 [Estado] char(1) NOT NULL DEFAULT ('A'),
 [RegistradoPor] int NOT NULL
);

CREATE TABLE Credito.ParametroPolitica (
 [IdParametro] int IDENTITY(1,1) NOT NULL,
 [Clave] varchar(50) NOT NULL,
 [Valor] decimal(18,6) NOT NULL,
 [Unidad] varchar(15) NOT NULL,
 [Descripcion] varchar(250) NULL,
 [VigenciaDesde] date NOT NULL,
 [VigenciaHasta] date NULL,
 [ModificadoPor] int NOT NULL,
 [Estado] varchar(10) NOT NULL DEFAULT ('Activo')
);

ALTER TABLE Canal.Canal ADD CONSTRAINT [PK_Canal] PRIMARY KEY ([IdCanal]);

CREATE UNIQUE INDEX [UQ_Canal_Codigo] ON Canal.Canal([CodigoCanal]);

CREATE UNIQUE INDEX [UQ_Canal_Nombre] ON Canal.Canal([NombreCanal]);

CREATE INDEX [IX_CanalCupoClienteCustom_Canal] ON Canal.CanalCupoClienteCustom([IdCanal]);

ALTER TABLE Canal.CanalCupoClienteCustom ADD CONSTRAINT [PK_CanalCupoClienteCustom] PRIMARY KEY ([IdCanalCupo]);

CREATE UNIQUE INDEX [UQ_CanalCupoClienteCustom] ON Canal.CanalCupoClienteCustom([IdCuenta],[IdCanal]);

CREATE INDEX [IX_CuposModHis_CanalCupo] ON Canal.CuposModHis([IdCanalCupoCliente],[FechaModificacion]);

ALTER TABLE Canal.CuposModHis ADD CONSTRAINT [PK_CuposModHis] PRIMARY KEY ([IdCupoModHis]);

CREATE INDEX [IX_Ciudad_Pais] ON Catalogo.Ciudad([CodigoPais]);

ALTER TABLE Catalogo.Ciudad ADD CONSTRAINT [PK_Ciudad] PRIMARY KEY ([IdCiudad]);

CREATE UNIQUE INDEX [UQ_Ciudad] ON Catalogo.Ciudad([CodigoPais],[Nombre]);

ALTER TABLE Catalogo.SistemaAmortizacion ADD CONSTRAINT [PK_SistemaAmortizacion] PRIMARY KEY ([Codigo]);

CREATE INDEX [IX_Cliente_ActividadEconomica] ON Clientes.Cliente([IdActividadEconomica]);

CREATE INDEX [IX_Cliente_CodigoPais] ON Clientes.Cliente([CodigoPaisNacionalidad]);

ALTER TABLE Clientes.Cliente ADD CONSTRAINT [PK_Cliente] PRIMARY KEY ([IdCliente]);

CREATE UNIQUE INDEX [UQ_Cliente_Identificacion] ON Clientes.Cliente([Identificacion]);

CREATE INDEX [IX_RiesgoCliente_IdCliente] ON Clientes.RiesgoCliente([IdCliente]);

ALTER TABLE Clientes.RiesgoCliente ADD CONSTRAINT [PK_RiesgoCliente] PRIMARY KEY ([IdEvaluacion]);

CREATE UNIQUE INDEX [UX_RiesgoCliente_Vigente] ON Clientes.RiesgoCliente([IdCliente]) WHERE ([EsVigente]=(1));

ALTER TABLE Contabilidad.FechaContable ADD CONSTRAINT [PK_FechaContable] PRIMARY KEY ([IdFechaContable]);

CREATE UNIQUE INDEX [UQ_FechaContable] ON Contabilidad.FechaContable([Fecha]);

CREATE INDEX [IX_CreditoDesembolso_Solicitud] ON Credito.CreditoDesembolso([IdSolicitud]);

ALTER TABLE Credito.CreditoDesembolso ADD CONSTRAINT [PK_CreditoDesembolso] PRIMARY KEY ([IdDesembolso]);

CREATE UNIQUE INDEX [UQ_CreditoDesembolso_Numero] ON Credito.CreditoDesembolso([NumeroDesembolso]);

CREATE UNIQUE INDEX [UX_CreditoDesembolso_Transaccion] ON Credito.CreditoDesembolso([IdTransaccionDesembolso]) WHERE ([IdTransaccionDesembolso] IS NOT NULL);

CREATE INDEX [IX_CreditoSolicitud_Cliente] ON Credito.CreditoSolicitud([IdCliente],[Estado]);

CREATE INDEX [IX_CreditoSolicitud_IdGarante] ON Credito.CreditoSolicitud([IdGarante]);

ALTER TABLE Credito.CreditoSolicitud ADD CONSTRAINT [PK_CreditoSolicitud] PRIMARY KEY ([IdSolicitud]);

CREATE UNIQUE INDEX [UQ_CreditoSolicitud_Numero] ON Credito.CreditoSolicitud([NumeroSolicitud]);

CREATE UNIQUE INDEX [UQ_CreditoSolicitud_Solicitud_Cliente_Tipo] ON Credito.CreditoSolicitud([IdSolicitud],[IdCliente],[IdTipoCredito]);

ALTER TABLE Credito.Seguro ADD CONSTRAINT [PK_Seguro] PRIMARY KEY ([IdSeguro]);

CREATE UNIQUE INDEX [UQ_Seguro_Codigo] ON Credito.Seguro([CodigoSeguro]);

CREATE INDEX [IX_TasaInteres_TipoCredito] ON Credito.TasaInteres([IdTipoCredito]);

ALTER TABLE Credito.TasaInteres ADD CONSTRAINT [PK_TasaInteres] PRIMARY KEY ([IdTasaInteres]);

ALTER TABLE Credito.TipoCredito ADD CONSTRAINT [PK_TipoCredito] PRIMARY KEY ([IdTipoCredito]);

CREATE UNIQUE INDEX [UQ_TipoCredito_Codigo] ON Credito.TipoCredito([CodigoTipoCredito]);

CREATE INDEX [IX_Cuenta_IdAgencia] ON Cuentas.Cuenta([IdAgencia]);

CREATE INDEX [IX_Cuenta_IdCliente] ON Cuentas.Cuenta([IdCliente]);

CREATE INDEX [IX_Cuenta_IdProducto] ON Cuentas.Cuenta([IdProducto]);

ALTER TABLE Cuentas.Cuenta ADD CONSTRAINT [PK_Cuenta] PRIMARY KEY ([IdCuenta]);

CREATE UNIQUE INDEX [UQ_Cuenta_Cuenta_Cliente] ON Cuentas.Cuenta([IdCuenta],[IdCliente]);

CREATE UNIQUE INDEX [UQ_Cuenta_Numero] ON Cuentas.Cuenta([NumeroCuenta]);

CREATE INDEX [IX_MovimientoTransaccion_IdTransaccion] ON Cuentas.MovimientoTransaccion([IdTransaccion]);

ALTER TABLE Cuentas.MovimientoTransaccion ADD CONSTRAINT [PK_MovimientoTransaccion] PRIMARY KEY ([IdMovimiento]);

CREATE UNIQUE INDEX [UQ_MovimientoTransaccion_Transaccion_Cuenta] ON Cuentas.MovimientoTransaccion([IdTransaccion],[IdCuenta]);

ALTER TABLE Organizacion.Agencia ADD CONSTRAINT [PK_Agencia] PRIMARY KEY ([IdAgencia]);

CREATE UNIQUE INDEX [UQ_Agencia_Codigo] ON Organizacion.Agencia([Codigo]);

CREATE UNIQUE INDEX [UX_Agencia_KeyAgencia] ON Organizacion.Agencia([KeyAgencia]) WHERE ([KeyAgencia] IS NOT NULL);

CREATE UNIQUE INDEX [UX_Agencia_UnaMatriz] ON Organizacion.Agencia([TipoAgencia]) WHERE ([TipoAgencia]='Matriz');

CREATE INDEX [IX_Producto_TipoCredito] ON ProductosFinancieros.Producto([IdTipoCredito]);

ALTER TABLE ProductosFinancieros.Producto ADD CONSTRAINT [PK_Producto] PRIMARY KEY ([IdProducto]);

CREATE UNIQUE INDEX [UQ_Producto_Codigo] ON ProductosFinancieros.Producto([CodigoProducto]);

CREATE INDEX [IX_E301_Cupo_ConsultaVigente] ON ProductosFinancieros.ProductoCanalCupo([IdSubProducto],[IdCanal],[VigenciaDesde]);

CREATE INDEX [IX_ProductoCanalCupo_Canal] ON ProductosFinancieros.ProductoCanalCupo([IdCanal]);

ALTER TABLE ProductosFinancieros.ProductoCanalCupo ADD CONSTRAINT [PK_ProductoCanalCupo] PRIMARY KEY ([IdProductoCanalCupo]);

CREATE UNIQUE INDEX [UX_E301_Cupo_VigenciaDesde] ON ProductosFinancieros.ProductoCanalCupo([IdSubProducto],[IdCanal],[VigenciaDesde]) WHERE ([EstadoCupo]='A');

ALTER TABLE ProductosFinancieros.ProductoComision ADD CONSTRAINT [PK_ProductoComision] PRIMARY KEY ([IdVinculo]);

CREATE UNIQUE INDEX [UX_ProductoComision_Producto] ON ProductosFinancieros.ProductoComision([IdProducto],[IdComision]) WHERE ([IdProducto] IS NOT NULL);

CREATE UNIQUE INDEX [UX_ProductoComision_SubProducto] ON ProductosFinancieros.ProductoComision([IdSubProducto],[IdComision]) WHERE ([IdSubProducto] IS NOT NULL);

ALTER TABLE ProductosFinancieros.ProductoRestriccion ADD CONSTRAINT [PK_ProductoRestriccion] PRIMARY KEY ([IdRestriccion]);

CREATE UNIQUE INDEX [UX_ProductoRestriccion_Activa] ON ProductosFinancieros.ProductoRestriccion([IdSubProducto],[TipoRestriccion]) WHERE ([Estado]='A');

ALTER TABLE ProductosFinancieros.ProductoSeguro ADD CONSTRAINT [PK_ProductoSeguro] PRIMARY KEY ([IdVinculo]);

CREATE UNIQUE INDEX [UX_ProductoSeguro_Producto] ON ProductosFinancieros.ProductoSeguro([IdProducto],[IdSeguro]) WHERE ([IdProducto] IS NOT NULL);

CREATE UNIQUE INDEX [UX_ProductoSeguro_SubProducto] ON ProductosFinancieros.ProductoSeguro([IdSubProducto],[IdSeguro]) WHERE ([IdSubProducto] IS NOT NULL);

ALTER TABLE ProductosFinancieros.ProductoSistemaAmortizacion ADD CONSTRAINT [PK_ProductoSistemaAmortizacion] PRIMARY KEY ([IdVinculo]);

CREATE UNIQUE INDEX [UX_ProductoSistemaAmortizacion_Producto] ON ProductosFinancieros.ProductoSistemaAmortizacion([IdProducto],[CodigoSistema]) WHERE ([IdProducto] IS NOT NULL);

CREATE UNIQUE INDEX [UX_ProductoSistemaAmortizacion_SubProducto] ON ProductosFinancieros.ProductoSistemaAmortizacion([IdSubProducto],[CodigoSistema]) WHERE ([IdSubProducto] IS NOT NULL);

ALTER TABLE ProductosFinancieros.ProductoTasaInteres ADD CONSTRAINT [PK_ProductoTasaInteres] PRIMARY KEY ([IdVinculo]);

CREATE UNIQUE INDEX [UX_ProductoTasaInteres_Producto] ON ProductosFinancieros.ProductoTasaInteres([IdProducto],[IdTasaInteres]) WHERE ([IdProducto] IS NOT NULL);

CREATE UNIQUE INDEX [UX_ProductoTasaInteres_SubProducto] ON ProductosFinancieros.ProductoTasaInteres([IdSubProducto],[IdTasaInteres]) WHERE ([IdSubProducto] IS NOT NULL);

ALTER TABLE ProductosFinancieros.Red ADD CONSTRAINT [PK_Red] PRIMARY KEY ([IdRed]);

CREATE UNIQUE INDEX [UQ_Red_Codigo] ON ProductosFinancieros.Red([CodigoRed]);

CREATE UNIQUE INDEX [UQ_Red_Nombre] ON ProductosFinancieros.Red([Nombre]);

CREATE INDEX [IX_SubProducto_Producto] ON ProductosFinancieros.SubProducto([IdProducto]);

ALTER TABLE ProductosFinancieros.SubProducto ADD CONSTRAINT [PK_SubProducto] PRIMARY KEY ([IdSubProducto]);

CREATE UNIQUE INDEX [UQ_SubProducto_Codigo] ON ProductosFinancieros.SubProducto([CodigoSubProducto]);

CREATE UNIQUE INDEX [UQ_SubProducto_SubProducto_Producto] ON ProductosFinancieros.SubProducto([IdSubProducto],[IdProducto]);

CREATE UNIQUE INDEX [UX_SubProducto_BIN] ON ProductosFinancieros.SubProducto([IdBIN]) WHERE ([IdBIN] IS NOT NULL);

ALTER TABLE ProductosFinancieros.SubProductoCondicion ADD CONSTRAINT [PK_E301_SubProductoCondicion] PRIMARY KEY ([IdCondicion]);

ALTER TABLE ProductosFinancieros.TipoProducto ADD CONSTRAINT [PK_TipoProducto] PRIMARY KEY ([IdTipoProducto]);

CREATE UNIQUE INDEX [UQ_TipoProducto_Codigo] ON ProductosFinancieros.TipoProducto([Codigo]);

ALTER TABLE ProductosFinancieros.TipoRestriccion ADD CONSTRAINT [PK_TipoRestriccion] PRIMARY KEY ([Codigo]);

CREATE INDEX [IX_Tarjeta_BIN] ON Tarjeta.Tarjeta([IdBIN]);

CREATE INDEX [IX_Tarjeta_IdCliente] ON Tarjeta.Tarjeta([IdCliente]);

CREATE INDEX [IX_Tarjeta_IdCuenta] ON Tarjeta.Tarjeta([IdCuenta]);

CREATE INDEX [IX_Tarjeta_IdTarjetaTitular] ON Tarjeta.Tarjeta([IdTarjetaTitular]);

ALTER TABLE Tarjeta.Tarjeta ADD CONSTRAINT [PK_Tarjeta] PRIMARY KEY ([IdTarjeta]);

CREATE UNIQUE INDEX [UQ_Tarjeta_Hash] ON Tarjeta.Tarjeta([HashNumeroTarjeta]);

CREATE UNIQUE INDEX [UQ_Tarjeta_Tarjeta_Cuenta] ON Tarjeta.Tarjeta([IdTarjeta],[IdCuenta]);

CREATE UNIQUE INDEX [UQ_Tarjeta_Token] ON Tarjeta.Tarjeta([TokenTarjeta]);

CREATE INDEX [IX_Comisiones_IdCanal] ON Transacciones.Comisiones([IdCanal]);

ALTER TABLE Transacciones.Comisiones ADD CONSTRAINT [PK_Comisiones] PRIMARY KEY ([IdComision]);

CREATE UNIQUE INDEX [UQ_Comisiones_Codigo] ON Transacciones.Comisiones([CodigoComision]);

CREATE UNIQUE INDEX [UQ_Comisiones_Comision_Canal] ON Transacciones.Comisiones([IdComision],[IdCanal]);

ALTER TABLE Transacciones.TipoTransaccion ADD CONSTRAINT [PK_TipoTransaccion] PRIMARY KEY ([CodigoTipo]);

CREATE UNIQUE INDEX [UQ_TipoTransaccion_Nombre] ON Transacciones.TipoTransaccion([Nombre]);

CREATE INDEX [IX_Transaccion_Cuenta_Fecha] ON Transacciones.Transaccion([IdCuenta],[IdFechaContable]);

CREATE INDEX [IX_Transaccion_FechaContable] ON Transacciones.Transaccion([IdFechaContable],[Estado]);

CREATE INDEX [IX_Transaccion_IdAgencia] ON Transacciones.Transaccion([IdAgencia]);

CREATE INDEX [IX_Transaccion_IdCanal] ON Transacciones.Transaccion([IdCanal]);

CREATE INDEX [IX_Transaccion_IdCiudad] ON Transacciones.Transaccion([IdCiudad]);

CREATE INDEX [IX_Transaccion_IdCuentaDestino] ON Transacciones.Transaccion([IdCuentaDestino]);

CREATE INDEX [IX_Transaccion_IdTerminal] ON Transacciones.Transaccion([IdATM]);

CREATE INDEX [IX_Transaccion_JornadaCaja] ON Transacciones.Transaccion([IdJornadaCaja]);

CREATE INDEX [IX_Transaccion_Relacionada] ON Transacciones.Transaccion([IdTransaccionRelacionada]);

CREATE INDEX [IX_Transaccion_Tarjeta_Fecha] ON Transacciones.Transaccion([IdTarjeta],[IdFechaContable]);

ALTER TABLE Transacciones.Transaccion ADD CONSTRAINT [PK_Transaccion] PRIMARY KEY ([IdTransaccion]);

CREATE UNIQUE INDEX [UQ_Transaccion_Comprobante] ON Transacciones.Transaccion([NumeroComprobante]);

CREATE UNIQUE INDEX [UQ_Transaccion_RegistroUnico] ON Transacciones.Transaccion([RegistroUnico]);

CREATE UNIQUE INDEX [UQ_Transaccion_Transaccion_Jornada] ON Transacciones.Transaccion([IdTransaccion],[IdJornadaCaja]);

CREATE UNIQUE INDEX [UX_Transaccion_UnReverso] ON Transacciones.Transaccion([IdTransaccionRelacionada]) WHERE ([TipoOperacion]='Reverso');

ALTER TABLE Credito.TasaInteres ADD CONSTRAINT [CK_TasaInteres_Montos] CHECK ([MontoMinimo] IS NULL OR [MontoMaximo] IS NULL OR [MontoMaximo]>=[MontoMinimo]);

ALTER TABLE ProductosFinancieros.ProductoTasaInteres ADD CONSTRAINT [CK_ProductoTasaInteres_Estado] CHECK ([Estado]='I' OR [Estado]='A');

ALTER TABLE ProductosFinancieros.ProductoTasaInteres ADD CONSTRAINT [CK_ProductoTasaInteres_Destino] CHECK ([IdProducto] IS NULL AND [IdSubProducto] IS NOT NULL OR [IdProducto] IS NOT NULL AND [IdSubProducto] IS NULL);

ALTER TABLE Contabilidad.FechaContable ADD CONSTRAINT [CK_FechaContable_DiaSemana] CHECK ([NumeroDiaSemana]>=(1) AND [NumeroDiaSemana]<=(7) AND [NumeroDiaSemana]=(datediff(day,CONVERT([date],'19000101',(112)),[Fecha])%(7)+(1)) AND [NombreDiaSemana]=case [NumeroDiaSemana] when (1) then N'Lunes' when (2) then N'Martes' when (3) then N'Miércoles' when (4) then N'Jueves' when (5) then N'Viernes' when (6) then N'Sábado' when (7) then N'Domingo'  end);

ALTER TABLE Credito.CreditoSolicitud ADD CONSTRAINT [CK_CreditoSolicitud_TipoRevision] CHECK ([TipoRevision] IS NULL OR ([TipoRevision]='Manual' OR [TipoRevision]='Automatica'));

ALTER TABLE Credito.CreditoSolicitud ADD CONSTRAINT [CK_CreditoSolicitud_AprobadoPor] CHECK ([TipoRevision]<>'Manual' OR [AprobadoPor] IS NOT NULL);

ALTER TABLE Transacciones.Comisiones ADD CONSTRAINT [CK_Comisiones_Rango] CHECK ([MontoMinimo] IS NULL OR [MontoMaximo] IS NULL OR [MontoMaximo]>=[MontoMinimo]);

ALTER TABLE ProductosFinancieros.ProductoComision ADD CONSTRAINT [CK_ProductoComision_Estado] CHECK ([Estado]='I' OR [Estado]='A');

ALTER TABLE Transacciones.Comisiones ADD CONSTRAINT [CK_Comisiones_MontosSegunCalculo] CHECK ([TipoCalculo]='Fijo' AND [MontoMinimo] IS NULL AND [MontoMaximo] IS NULL OR [TipoCalculo]='Porcentaje' AND [MontoMinimo] IS NOT NULL AND [MontoMaximo] IS NOT NULL);

ALTER TABLE Transacciones.Transaccion ADD CONSTRAINT [CK_Transaccion_Monto] CHECK ([TipoTransaccion]='Consulta' AND [Monto]>=(0) OR [TipoTransaccion]<>'Consulta' AND [Monto]>(0));

ALTER TABLE Clientes.Cliente ADD CONSTRAINT [CK_Cliente_Estado] CHECK ([Estado]='Eliminado' OR [Estado]='Bloqueado' OR [Estado]='Suspendido' OR [Estado]='Inactivo' OR [Estado]='Activo' OR [Estado]='Pendiente');

ALTER TABLE ProductosFinancieros.ProductoComision ADD CONSTRAINT [CK_ProductoComision_Destino] CHECK ([IdProducto] IS NULL AND [IdSubProducto] IS NOT NULL OR [IdProducto] IS NOT NULL AND [IdSubProducto] IS NULL);

ALTER TABLE ProductosFinancieros.ProductoComision ADD CONSTRAINT [CK_ProductoComision_Exonerado] CHECK ([Exonerado]=(0) OR [IdSubProducto] IS NOT NULL);

ALTER TABLE Credito.Seguro ADD CONSTRAINT [CK_Seguro_Calculo] CHECK ([TipoCalculo]='Porcentaje' OR [TipoCalculo]='Fijo');

ALTER TABLE Tarjeta.Tarjeta ADD CONSTRAINT [CK_Tarjeta_Tipo] CHECK ([TipoTarjeta]='Credito' OR [TipoTarjeta]='Debito');

ALTER TABLE Credito.Seguro ADD CONSTRAINT [CK_Seguro_Valor] CHECK ([Valor]>=(0));

ALTER TABLE Credito.Seguro ADD CONSTRAINT [CK_Seguro_Estado] CHECK ([Estado]='I' OR [Estado]='A');

ALTER TABLE Tarjeta.Tarjeta ADD CONSTRAINT [CK_Tarjeta_Extension] CHECK ([EsExtension]=(0) AND [IdTarjetaTitular] IS NULL OR [EsExtension]=(1) AND [IdTarjetaTitular] IS NOT NULL);

ALTER TABLE Credito.Seguro ADD CONSTRAINT [CK_Seguro_Porcentaje] CHECK ([TipoCalculo]<>'Porcentaje' OR [Valor]<=(100));

ALTER TABLE Credito.CreditoDesembolso ADD CONSTRAINT [CK_CreditoDesembolso_Tasa] CHECK ([TasaNominalAnual]>(0) AND [TasaNominalAnual]<=(1));

ALTER TABLE Tarjeta.Tarjeta ADD CONSTRAINT [CK_Tarjeta_Fechas] CHECK ([FechaExpiracion]>[FechaEmision]);

ALTER TABLE Transacciones.TipoTransaccion ADD CONSTRAINT [CK_TipoTransaccion_Naturaleza] CHECK ([AfectaSaldo]=(1) AND ([Naturaleza]='D' OR [Naturaleza]='C') OR [AfectaSaldo]=(0) AND [Naturaleza] IS NULL);

ALTER TABLE Credito.Seguro ADD CONSTRAINT [CK_Seguro_Vigencia] CHECK ([VigenciaHasta] IS NULL OR [VigenciaHasta]>[VigenciaDesde]);

ALTER TABLE Credito.CreditoDesembolso ADD CONSTRAINT [CK_CreditoDesembolso_Estado] CHECK ([Estado]='REVERSADO' OR [Estado]='DESEMBOLSADO' OR [Estado]='PENDIENTE');

ALTER TABLE Transacciones.TipoTransaccion ADD CONSTRAINT [CK_TipoTransaccion_Estado] CHECK ([Estado]='I' OR [Estado]='A');

ALTER TABLE Credito.CreditoDesembolso ADD CONSTRAINT [CK_CreditoDesembolso_Ejecutado] CHECK ([Estado]<>'DESEMBOLSADO' OR [IdTransaccionDesembolso] IS NOT NULL AND [DesembolsadoPor] IS NOT NULL AND [FechaDesembolso] IS NOT NULL);

ALTER TABLE ProductosFinancieros.ProductoSeguro ADD CONSTRAINT [CK_ProductoSeguro_Estado] CHECK ([Estado]='I' OR [Estado]='A');

ALTER TABLE Credito.CreditoSolicitud ADD CONSTRAINT [CK_CreditoSolicitud_Estado] CHECK ([Estado]='RECHAZADA' OR [Estado]='APROBADA' OR [Estado]='REVISION_MANUAL' OR [Estado]='DESISTIDA');

ALTER TABLE ProductosFinancieros.ProductoSeguro ADD CONSTRAINT [CK_ProductoSeguro_Destino] CHECK ([IdProducto] IS NULL AND [IdSubProducto] IS NOT NULL OR [IdProducto] IS NOT NULL AND [IdSubProducto] IS NULL);

ALTER TABLE Credito.TipoCredito ADD CONSTRAINT [CK_TipoCredito_Estado] CHECK ([Estado]='I' OR [Estado]='A');

ALTER TABLE Cuentas.Cuenta ADD CONSTRAINT [CK_Cuenta_Saldo] CHECK ([Saldo]>=(0));

ALTER TABLE Cuentas.Cuenta ADD CONSTRAINT [CK_Cuenta_Cierre] CHECK ([Estado]<>'Cerrada' OR [Saldo]=(0) AND [SaldoRetenido]=(0) AND [FechaCierre] IS NOT NULL);

ALTER TABLE Cuentas.Cuenta ADD CONSTRAINT [CK_Cuenta_Retenido] CHECK ([SaldoRetenido]>=(0) AND [SaldoRetenido]<=[Saldo]);

ALTER TABLE ProductosFinancieros.ProductoSistemaAmortizacion ADD CONSTRAINT [CK_ProductoSistemaAmortizacion_Estado] CHECK ([Estado]='I' OR [Estado]='A');

ALTER TABLE ProductosFinancieros.ProductoSistemaAmortizacion ADD CONSTRAINT [CK_ProductoSistemaAmortizacion_Destino] CHECK ([IdProducto] IS NULL AND [IdSubProducto] IS NOT NULL OR [IdProducto] IS NOT NULL AND [IdSubProducto] IS NULL);

ALTER TABLE Transacciones.Transaccion ADD CONSTRAINT [CK_Transaccion_TransferenciaDestino] CHECK ([TipoTransaccion]<>'Transferencia_Enviada' OR [IdCuentaDestino] IS NOT NULL);

ALTER TABLE ProductosFinancieros.SubProducto ADD CONSTRAINT [CK_SubProducto_Edades] CHECK (([EdadMinima] IS NULL OR [EdadMinima]<=(120)) AND ([EdadMaxima] IS NULL OR [EdadMaxima]<=(120)) AND ([EdadMinima] IS NULL OR [EdadMaxima] IS NULL OR [EdadMaxima]>=[EdadMinima]));

ALTER TABLE Credito.TasaInteres ADD CONSTRAINT [CK_TasaInteres_Tasa] CHECK ([TasaNominalAnual]>(0) AND [TasaNominalAnual]<=(1));

ALTER TABLE Credito.TasaInteres ADD CONSTRAINT [CK_TasaInteres_Vigencia] CHECK ([VigenciaHasta] IS NULL OR [VigenciaHasta]>[VigenciaDesde]);

ALTER TABLE Cuentas.MovimientoTransaccion ADD CONSTRAINT [CK_MovimientoTransaccion_Monto] CHECK ([Monto]>(0));

ALTER TABLE Clientes.Cliente ADD CONSTRAINT [CK_Cliente_Nacimiento] CHECK ([FechaNacimiento]<CONVERT([date],sysdatetime()));

ALTER TABLE ProductosFinancieros.TipoProducto ADD CONSTRAINT [CK_TipoProducto_Estado] CHECK ([Estado]='I' OR [Estado]='A');

ALTER TABLE Clientes.Cliente ADD CONSTRAINT [CK_Cliente_TipoDocumento] CHECK ([TipoDocumento]='R' OR [TipoDocumento]='P' OR [TipoDocumento]='C');

ALTER TABLE Transacciones.Comisiones ADD CONSTRAINT [CK_Comisiones_Tipo] CHECK ([TipoComision]='Otro' OR [TipoComision]='Consulta' OR [TipoComision]='Mantenimiento' OR [TipoComision]='Reposicion Tarjeta' OR [TipoComision]='Emision Tarjeta' OR [TipoComision]='Retiro' OR [TipoComision]='Transferencia');

ALTER TABLE Clientes.Cliente ADD CONSTRAINT [CK_Cliente_TipoCliente] CHECK ([TipoCliente]='Juridico' OR [TipoCliente]='Natural');

ALTER TABLE Transacciones.Comisiones ADD CONSTRAINT [CK_Comisiones_Calculo] CHECK ([TipoCalculo]='Porcentaje' OR [TipoCalculo]='Fijo');

ALTER TABLE Cuentas.MovimientoTransaccion ADD CONSTRAINT [CK_MovimientoTransaccion_Cuadre] CHECK ([TipoMovimiento]='C' AND [SaldoPosterior]=([SaldoAnterior]+[Monto]) OR [TipoMovimiento]='D' AND [SaldoPosterior]=([SaldoAnterior]-[Monto]));

ALTER TABLE Clientes.Cliente ADD CONSTRAINT [CK_Cliente_Genero] CHECK ([Genero]='M' OR [Genero]='F');

ALTER TABLE Transacciones.Comisiones ADD CONSTRAINT [CK_Comisiones_Valor] CHECK ([Valor]>=(0));

ALTER TABLE Cuentas.MovimientoTransaccion ADD CONSTRAINT [CK_MovimientoTransaccion_Saldos] CHECK ([SaldoAnterior]>=(0) AND [SaldoPosterior]>=(0));

ALTER TABLE Clientes.Cliente ADD CONSTRAINT [CK_Cliente_EstadoCivil] CHECK ([EstadoCivil]='Union Libre' OR [EstadoCivil]='Viudo' OR [EstadoCivil]='Divorciado' OR [EstadoCivil]='Casado' OR [EstadoCivil]='Soltero');

ALTER TABLE Transacciones.Comisiones ADD CONSTRAINT [CK_Comisiones_Estado] CHECK ([Estado]='I' OR [Estado]='A');

ALTER TABLE Transacciones.Comisiones ADD CONSTRAINT [CK_Comisiones_Porcentaje] CHECK ([TipoCalculo]<>'Porcentaje' OR [Valor]<=(100));

ALTER TABLE Clientes.Cliente ADD CONSTRAINT [CK_Cliente_TipoPersona] CHECK ([TipoCliente]='Natural' AND [Apellidos] IS NOT NULL AND [Genero] IS NOT NULL AND [EstadoCivil] IS NOT NULL OR [TipoCliente]='Juridico' AND [RazonSocial] IS NOT NULL AND [Apellidos] IS NULL AND [Genero] IS NULL AND [EstadoCivil] IS NULL);

ALTER TABLE Transacciones.Comisiones ADD CONSTRAINT [CK_Comisiones_Vigencia] CHECK ([VigenciaHasta] IS NULL OR [VigenciaHasta]>[VigenciaDesde]);

ALTER TABLE ProductosFinancieros.Producto ADD CONSTRAINT [CK_E301_Producto_EstadoProducto] CHECK ([EstadoProducto]='Retirado' OR [EstadoProducto]='Suspendido' OR [EstadoProducto]='Activo' OR [EstadoProducto]='Borrador');

ALTER TABLE ProductosFinancieros.SubProducto ADD CONSTRAINT [CK_E301_SubProducto_EstadoSubProducto] CHECK ([EstadoSubProducto]='Retirado' OR [EstadoSubProducto]='Suspendido' OR [EstadoSubProducto]='Activo' OR [EstadoSubProducto]='Borrador');

ALTER TABLE ProductosFinancieros.SubProducto ADD CONSTRAINT [CK_E301_SubProducto_TipoCliente] CHECK ([TipoClientePermitido]='Ambos' OR [TipoClientePermitido]='Juridico' OR [TipoClientePermitido]='Natural');

ALTER TABLE ProductosFinancieros.SubProducto ADD CONSTRAINT [CK_E301_SubProducto_Maximo] CHECK ([MaximoPorCliente] IS NULL OR [MaximoPorCliente]>(0));

ALTER TABLE Clientes.Cliente ADD CONSTRAINT [CK_Cliente_Consentimiento] CHECK ([ConsentimientoDatos]=(1));

ALTER TABLE Clientes.Cliente ADD CONSTRAINT [CK_Cliente_Identificacion] CHECK ([TipoDocumento]='C' AND len([Identificacion])=(10) AND NOT [Identificacion] like '%[^0-9]%' OR [TipoDocumento]='R' AND len([Identificacion])=(13) AND NOT [Identificacion] like '%[^0-9]%' AND right([Identificacion],(3))='001' OR [TipoDocumento]='P' AND (len([Identificacion])>=(5) AND len([Identificacion])<=(13)) AND NOT [Identificacion] like '%[^0-9A-Z]%');

ALTER TABLE ProductosFinancieros.SubProductoCondicion ADD CONSTRAINT [CK_E301_Condicion_Montos] CHECK ([MontoAperturaMinimo]>=(0) AND [SaldoMinimo]>=(0) AND [SaldoMinimo]<=[MontoAperturaMinimo] AND [CostoMantenimiento]>=(0) AND ([TasaInteresAnual]>=(0) AND [TasaInteresAnual]<=(100)));

ALTER TABLE ProductosFinancieros.SubProductoCondicion ADD CONSTRAINT [CK_E301_Condicion_Estado] CHECK ([Estado]='Cancelada' OR [Estado]='Reemplazada' OR [Estado]='Vigente' OR [Estado]='Programada' OR [Estado]='Pendiente');

ALTER TABLE ProductosFinancieros.SubProductoCondicion ADD CONSTRAINT [CK_E301_Condicion_Vigencia] CHECK ([VigenciaHasta] IS NULL OR [VigenciaHasta]>=[VigenciaDesde]);

ALTER TABLE ProductosFinancieros.SubProductoCondicion ADD CONSTRAINT [CK_E301_Condicion_Inactividad] CHECK ([MesesInactividad] IS NULL OR [MesesInactividad]>(0));

ALTER TABLE ProductosFinancieros.Red ADD CONSTRAINT [CK_Red_Condiciones] CHECK (([IngresoMinimo] IS NULL OR [IngresoMinimo]>=(0)) AND ([EdadMinima] IS NULL OR [EdadMinima]>=(16) AND [EdadMinima]<=(99)));

ALTER TABLE Clientes.RiesgoCliente ADD CONSTRAINT [CK_RiesgoCliente_Antecedente] CHECK ([TieneAntecedentes]=(0) AND [IdTipoAntecedente] IS NULL OR [TieneAntecedentes]=(1) AND [IdTipoAntecedente] IS NOT NULL);

ALTER TABLE ProductosFinancieros.Red ADD CONSTRAINT [CK_Red_Estado] CHECK ([Estado]='I' OR [Estado]='A');

ALTER TABLE Clientes.RiesgoCliente ADD CONSTRAINT [CK_RiesgoCliente_NivelRiesgoLAFT] CHECK ([NivelRiesgoLAFT]='Alto' OR [NivelRiesgoLAFT]='Medio' OR [NivelRiesgoLAFT]='Bajo');

ALTER TABLE ProductosFinancieros.ProductoCanalCupo ADD CONSTRAINT [CK_E301_Cupo_Vigencia] CHECK ([VigenciaHasta] IS NULL OR [VigenciaHasta]>=[VigenciaDesde]);

ALTER TABLE Transacciones.Transaccion ADD CONSTRAINT [CK_Transaccion_TipoOperacion] CHECK ([TipoOperacion]='Reverso' OR [TipoOperacion]='Normal');

ALTER TABLE Clientes.RiesgoCliente ADD CONSTRAINT [CK_RiesgoCliente_Resultado] CHECK ([ResultadoEvaluacion]='Rechazado' OR [ResultadoEvaluacion]='Observado' OR [ResultadoEvaluacion]='Aprobado');

ALTER TABLE ProductosFinancieros.ProductoCanalCupo ADD CONSTRAINT [CK_E301_Cupo_Estado] CHECK ([EstadoCupo]='I' OR [EstadoCupo]='A');

ALTER TABLE ProductosFinancieros.Producto ADD CONSTRAINT [CK_Producto_RedRequerida] CHECK ([TipoProducto]<>'Tarjeta' OR [IdRed] IS NOT NULL);

ALTER TABLE Cuentas.Cuenta ADD CONSTRAINT [CK_Cuenta_Estado] CHECK ([Estado]='Cerrada' OR [Estado]='Bloqueada' OR [Estado]='Inactiva' OR [Estado]='Activa');

ALTER TABLE Transacciones.Transaccion ADD CONSTRAINT [CK_Transaccion_Estado] CHECK ([Estado]='Rechazada' OR [Estado]='Reversada' OR [Estado]='Pendiente' OR [Estado]='Completada');

ALTER TABLE Tarjeta.Tarjeta ADD CONSTRAINT [CK_Tarjeta_Estado] CHECK ([Estado]='Cerrada' OR [Estado]='Vencida' OR [Estado]='Anulada' OR [Estado]='Cancelada' OR [Estado]='Bloqueada' OR [Estado]='Inactiva' OR [Estado]='Activa' OR [Estado]='Generada' OR [Estado]='Aprobada' OR [Estado]='Solicitada');

ALTER TABLE Transacciones.Transaccion ADD CONSTRAINT [CK_Transaccion_Autoreferencia] CHECK ([IdTransaccionRelacionada] IS NULL OR [IdTransaccionRelacionada]<>[IdTransaccion]);

ALTER TABLE Transacciones.Transaccion ADD CONSTRAINT [CK_Transaccion_Destino] CHECK ([IdCuentaDestino] IS NULL OR [IdCuentaDestino]<>[IdCuenta]);

ALTER TABLE Transacciones.Transaccion ADD CONSTRAINT [CK_Transaccion_MTI] CHECK ([TipoOperacion]='Normal' AND [MTI]='0200' OR [TipoOperacion]='Reverso' AND [MTI]='0400' AND [IdTransaccionRelacionada] IS NOT NULL);

ALTER TABLE Transacciones.Transaccion ADD CONSTRAINT [CK_Transaccion_Rechazo] CHECK ([Estado]='Rechazada' AND [CodigoRespuesta]<>'00' OR [Estado]<>'Rechazada' AND [CodigoRespuesta]='00');

ALTER TABLE ProductosFinancieros.Producto ADD CONSTRAINT [CK_Producto_Monto] CHECK ([MontoAperturaMinimo]>=(0));

ALTER TABLE ProductosFinancieros.ProductoRestriccion ADD CONSTRAINT [CK_ProductoRestriccion_Tipo] CHECK ([TipoRestriccion]='SIN_RETIROS' AND [Dias] IS NOT NULL AND [Dias]>(0) AND [Monto] IS NULL OR [TipoRestriccion]='SALDO_MINIMO' AND [Monto] IS NOT NULL AND [Monto]>(0) AND [Dias] IS NULL);

ALTER TABLE Cuentas.MovimientoTransaccion ADD CONSTRAINT [CK_MovimientoTransaccion_Tipo] CHECK ([TipoMovimiento]='C' OR [TipoMovimiento]='D');

ALTER TABLE ProductosFinancieros.ProductoRestriccion ADD CONSTRAINT [CK_ProductoRestriccion_Vigencia] CHECK ([VigenciaHasta] IS NULL OR [VigenciaHasta]>[VigenciaDesde]);

ALTER TABLE Credito.CreditoSolicitud ADD CONSTRAINT [CK_CreditoSolicitud_Monto] CHECK ([Monto]>(0));

ALTER TABLE Cuentas.MovimientoTransaccion ADD CONSTRAINT [CK_MovimientoTransaccion_RolCuenta] CHECK ([RolCuenta] IS NULL OR [RolCuenta]='Origen' OR [RolCuenta]='Destino');

ALTER TABLE ProductosFinancieros.ProductoRestriccion ADD CONSTRAINT [CK_ProductoRestriccion_Estado] CHECK ([Estado]='I' OR [Estado]='A');

ALTER TABLE ProductosFinancieros.ProductoCanalCupo ADD CONSTRAINT [CK_ProductoCanalCupo_Cupos] CHECK ([CupoDiarioMaximo]>(0) AND [CupoMensualMaximo]>=[CupoDiarioMaximo] AND [MontoMaxTransaccion]>(0) AND [MontoMaxTransaccion]<=[CupoDiarioMaximo]);

ALTER TABLE Canal.CanalCupoClienteCustom ADD CONSTRAINT [CK_CanalCupoClienteCustom_Cupos] CHECK ([CupoDiario]>(0) AND [CupoMensual]>=[CupoDiario] AND [MontoMaxTransaccion]>(0) AND [MontoMaxTransaccion]<=[CupoDiario]);

ALTER TABLE Credito.CreditoSolicitud ADD CONSTRAINT [CK_CreditoSolicitud_AprobadorDistinto] CHECK ([AprobadoPor] IS NULL OR [AprobadoPor]<>[CreadoPor]);

ALTER TABLE Credito.CreditoSolicitud ADD CONSTRAINT [CK_CreditoSolicitud_AprobadaCompleta] CHECK ([Estado]<>'APROBADA' OR [TipoRevision] IS NOT NULL AND [FechaResolucion] IS NOT NULL);

ALTER TABLE Credito.CreditoSolicitud ADD CONSTRAINT [CK_CreditoSolicitud_Tasa] CHECK ([TasaNominalAnual]>(0) AND [TasaNominalAnual]<=(1));

ALTER TABLE Credito.CreditoSolicitud ADD CONSTRAINT [CK_CreditoSolicitud_ConsentimientoBuro] CHECK ([IdReporteBuro] IS NULL OR [ConsienteConsultaBuro]=(1));

ALTER TABLE Organizacion.Agencia ADD CONSTRAINT [CK_Agencia_Tipo] CHECK ([TipoAgencia]='Sucursal' OR [TipoAgencia]='Matriz');

ALTER TABLE Credito.CreditoSolicitud ADD CONSTRAINT [CK_CreditoSolicitud_LicitudFondos] CHECK ([Estado]<>'APROBADA' OR [DeclaraLicitudFondos]=(1));

ALTER TABLE Organizacion.Agencia ADD CONSTRAINT [CK_Agencia_Estado] CHECK ([Estado]='C' OR [Estado]='I' OR [Estado]='A');

ALTER TABLE ProductosFinancieros.Producto ADD CONSTRAINT [CK_Producto_Tipo] CHECK ([TipoProducto]='Credito' OR [TipoProducto]='Tarjeta' OR [TipoProducto]='Cuenta');

ALTER TABLE ProductosFinancieros.Producto ADD CONSTRAINT [CK_Producto_Estado] CHECK ([Estado]='I' OR [Estado]='A');

ALTER TABLE ProductosFinancieros.Producto ADD CONSTRAINT [CK_Producto_TipoCreditoRequerido] CHECK ([TipoProducto]<>'Credito' OR [IdTipoCredito] IS NOT NULL);

ALTER TABLE ProductosFinancieros.Producto ADD CONSTRAINT [CK_Producto_TipoCuenta] CHECK ([TipoProducto]='Cuenta' AND ([TipoCuenta]='Corriente' OR [TipoCuenta]='Ahorro') OR [TipoProducto]<>'Cuenta' AND [TipoCuenta] IS NULL);

ALTER TABLE ProductosFinancieros.ProductoCanalCupo ADD CONSTRAINT [CK_ProductoCanalCupo_NumMax] CHECK ([MaxTransaccionesDia]>(0));

ALTER TABLE ProductosFinancieros.Producto ADD CONSTRAINT [CK_Producto_Descripcion] CHECK ([Descripcion] IS NULL OR len([Descripcion])>(0));

ALTER TABLE Catalogo.SistemaAmortizacion ADD CONSTRAINT [CK_SistemaAmortizacion_Estado] CHECK ([Estado]='I' OR [Estado]='A');

ALTER TABLE Credito.CreditoSolicitud ADD CONSTRAINT [CK_CreditoSolicitud_Plazo] CHECK ([PlazoMeses]>(0));

ALTER TABLE Credito.CreditoSolicitud ADD CONSTRAINT [CK_CreditoSolicitud_Sistema] CHECK ([SistemaAmortizacion]='ALEMAN' OR [SistemaAmortizacion]='FRANCES');

ALTER TABLE ProductosFinancieros.SubProducto ADD CONSTRAINT [CK_SubProducto_Estado] CHECK ([Estado]='I' OR [Estado]='A');

ALTER TABLE Canal.Canal ADD CONSTRAINT [CK_Canal_ModoDigitalPresencial] CHECK ([ModoDigitalPresencial] IS NULL OR [ModoDigitalPresencial]='Digital' OR [ModoDigitalPresencial]='Presencial' OR [ModoDigitalPresencial]='Ambos');

ALTER TABLE Canal.Canal ADD CONSTRAINT [CK_Canal_Estado] CHECK ([Estado]='I' OR [Estado]='A');

ALTER TABLE Catalogo.Ciudad ADD CONSTRAINT [CK_Ciudad_Estado] CHECK ([Estado]='I' OR [Estado]='A');

ALTER TABLE Credito.CreditoSolicitud ADD CONSTRAINT [CK_CreditoSolicitud_Resolucion] CHECK ([Estado]='REVISION_MANUAL' OR [Estado]='APROBADA' OR [FechaResolucion] IS NOT NULL);

ALTER TABLE Canal.Canal ADD CONSTRAINT [CK_Canal_Pin] CHECK ([RequierePin]=(0) OR [RequiereTarjeta]=(1));

ALTER TABLE Credito.TasaInteres ADD CONSTRAINT [CK_TasaInteres_Estado] CHECK ([Estado]='I' OR [Estado]='A');

ALTER TABLE Credito.CreditoDesembolso ADD CONSTRAINT [CK_CreditoDesembolso_Monto] CHECK ([MontoDesembolsado]>(0));

ALTER TABLE Tarjeta.Tarjeta ADD CONSTRAINT [CK_Tarjeta_ValorUltimo] CHECK ([ValorUltimoMovimiento] IS NULL OR [ValorUltimoMovimiento]>=(0));

ALTER TABLE Credito.TasaInteres ADD CONSTRAINT [CK_TasaInteres_TipoTasa] CHECK ([TipoTasa]='TARJETA_MORA' OR [TipoTasa]='TARJETA_EXTERIOR' OR [TipoTasa]='TARJETA_DIFERIDO' OR [TipoTasa]='TARJETA_AVANCE' OR [TipoTasa]='TARJETA_COMPRA' OR [TipoTasa]='AHORRO' OR [TipoTasa]='CREDITO');

ALTER TABLE Canal.CanalCupoClienteCustom ADD CONSTRAINT [CK_CanalCupoClienteCustom_NumMax] CHECK ([MaxTransaccionesDia]>(0));

ALTER TABLE Credito.TasaInteres ADD CONSTRAINT [CK_TasaInteres_Plazo] CHECK ([PlazoMaximoMeses] IS NULL OR [PlazoMaximoMeses]>(0));

ALTER TABLE Canal.CanalCupoClienteCustom ADD CONSTRAINT [CK_CanalCupoClienteCustom_Estado] CHECK ([Estado]='I' OR [Estado]='A');

ALTER TABLE Credito.TasaInteres ADD CONSTRAINT [CK_TasaInteres_TipoCredito] CHECK ([TipoTasa]='CREDITO' AND [IdTipoCredito] IS NOT NULL AND [PlazoMaximoMeses] IS NOT NULL OR [TipoTasa]<>'CREDITO' AND [IdTipoCredito] IS NULL);

-- FKs reales representadas, sin copiar datos ajenos.
IF NOT EXISTS(SELECT 1 FROM sys.foreign_keys WHERE name=N'FK_ProductoTasaInteres_Producto') ALTER TABLE ProductosFinancieros.ProductoTasaInteres WITH CHECK ADD CONSTRAINT [FK_ProductoTasaInteres_Producto] FOREIGN KEY([IdProducto]) REFERENCES ProductosFinancieros.Producto([IdProducto]);
IF NOT EXISTS(SELECT 1 FROM sys.foreign_keys WHERE name=N'FK_CanalCupoClienteCustom_Canal') ALTER TABLE Canal.CanalCupoClienteCustom WITH CHECK ADD CONSTRAINT [FK_CanalCupoClienteCustom_Canal] FOREIGN KEY([IdCanal]) REFERENCES Canal.Canal([IdCanal]);
IF NOT EXISTS(SELECT 1 FROM sys.foreign_keys WHERE name=N'FK_ProductoTasaInteres_SubProducto') ALTER TABLE ProductosFinancieros.ProductoTasaInteres WITH CHECK ADD CONSTRAINT [FK_ProductoTasaInteres_SubProducto] FOREIGN KEY([IdSubProducto]) REFERENCES ProductosFinancieros.SubProducto([IdSubProducto]);
IF NOT EXISTS(SELECT 1 FROM sys.foreign_keys WHERE name=N'FK_CuposModHis_CanalCupo') ALTER TABLE Canal.CuposModHis WITH CHECK ADD CONSTRAINT [FK_CuposModHis_CanalCupo] FOREIGN KEY([IdCanalCupoCliente]) REFERENCES Canal.CanalCupoClienteCustom([IdCanalCupo]);
IF NOT EXISTS(SELECT 1 FROM sys.foreign_keys WHERE name=N'FK_ProductoComision_Producto') ALTER TABLE ProductosFinancieros.ProductoComision WITH CHECK ADD CONSTRAINT [FK_ProductoComision_Producto] FOREIGN KEY([IdProducto]) REFERENCES ProductosFinancieros.Producto([IdProducto]);
IF NOT EXISTS(SELECT 1 FROM sys.foreign_keys WHERE name=N'FK_ProductoComision_SubProducto') ALTER TABLE ProductosFinancieros.ProductoComision WITH CHECK ADD CONSTRAINT [FK_ProductoComision_SubProducto] FOREIGN KEY([IdSubProducto]) REFERENCES ProductosFinancieros.SubProducto([IdSubProducto]);
IF NOT EXISTS(SELECT 1 FROM sys.foreign_keys WHERE name=N'FK_ProductoSeguro_Producto') ALTER TABLE ProductosFinancieros.ProductoSeguro WITH CHECK ADD CONSTRAINT [FK_ProductoSeguro_Producto] FOREIGN KEY([IdProducto]) REFERENCES ProductosFinancieros.Producto([IdProducto]);
IF NOT EXISTS(SELECT 1 FROM sys.foreign_keys WHERE name=N'FK_ProductoSeguro_SubProducto') ALTER TABLE ProductosFinancieros.ProductoSeguro WITH CHECK ADD CONSTRAINT [FK_ProductoSeguro_SubProducto] FOREIGN KEY([IdSubProducto]) REFERENCES ProductosFinancieros.SubProducto([IdSubProducto]);
IF NOT EXISTS(SELECT 1 FROM sys.foreign_keys WHERE name=N'FK_ComisionTipoTransaccion_Canal') ALTER TABLE Transacciones.ComisionTipoTransaccion WITH CHECK ADD CONSTRAINT [FK_ComisionTipoTransaccion_Canal] FOREIGN KEY([IdCanal]) REFERENCES Canal.Canal([IdCanal]);
IF NOT EXISTS(SELECT 1 FROM sys.foreign_keys WHERE name=N'FK_ProductoSistemaAmortizacion_Producto') ALTER TABLE ProductosFinancieros.ProductoSistemaAmortizacion WITH CHECK ADD CONSTRAINT [FK_ProductoSistemaAmortizacion_Producto] FOREIGN KEY([IdProducto]) REFERENCES ProductosFinancieros.Producto([IdProducto]);
IF NOT EXISTS(SELECT 1 FROM sys.foreign_keys WHERE name=N'FK_ProductoSistemaAmortizacion_SubProducto') ALTER TABLE ProductosFinancieros.ProductoSistemaAmortizacion WITH CHECK ADD CONSTRAINT [FK_ProductoSistemaAmortizacion_SubProducto] FOREIGN KEY([IdSubProducto]) REFERENCES ProductosFinancieros.SubProducto([IdSubProducto]);
IF NOT EXISTS(SELECT 1 FROM sys.foreign_keys WHERE name=N'FK_Tarjeta_Producto') ALTER TABLE Tarjeta.Tarjeta WITH CHECK ADD CONSTRAINT [FK_Tarjeta_Producto] FOREIGN KEY([IdProducto]) REFERENCES ProductosFinancieros.Producto([IdProducto]);
IF NOT EXISTS(SELECT 1 FROM sys.foreign_keys WHERE name=N'FK_E301_Producto_TipoProducto') ALTER TABLE ProductosFinancieros.Producto WITH CHECK ADD CONSTRAINT [FK_E301_Producto_TipoProducto] FOREIGN KEY([IdTipoProducto]) REFERENCES ProductosFinancieros.TipoProducto([IdTipoProducto]);
IF NOT EXISTS(SELECT 1 FROM sys.foreign_keys WHERE name=N'FK_CreditoSolicitud_Canal') ALTER TABLE Credito.CreditoSolicitud WITH CHECK ADD CONSTRAINT [FK_CreditoSolicitud_Canal] FOREIGN KEY([IdCanal]) REFERENCES Canal.Canal([IdCanal]);
IF NOT EXISTS(SELECT 1 FROM sys.foreign_keys WHERE name=N'FK_E301_SubProducto_Requerido') ALTER TABLE ProductosFinancieros.SubProducto WITH CHECK ADD CONSTRAINT [FK_E301_SubProducto_Requerido] FOREIGN KEY([IdSubProductoRequerido]) REFERENCES ProductosFinancieros.SubProducto([IdSubProducto]);
IF NOT EXISTS(SELECT 1 FROM sys.foreign_keys WHERE name=N'FK_E301_Condicion_SubProducto') ALTER TABLE ProductosFinancieros.SubProductoCondicion WITH CHECK ADD CONSTRAINT [FK_E301_Condicion_SubProducto] FOREIGN KEY([IdSubProducto]) REFERENCES ProductosFinancieros.SubProducto([IdSubProducto]);
IF NOT EXISTS(SELECT 1 FROM sys.foreign_keys WHERE name=N'FK_Producto_Red') ALTER TABLE ProductosFinancieros.Producto WITH CHECK ADD CONSTRAINT [FK_Producto_Red] FOREIGN KEY([IdRed]) REFERENCES ProductosFinancieros.Red([IdRed]);
IF NOT EXISTS(SELECT 1 FROM sys.foreign_keys WHERE name=N'FK_ProductoCanalCupo_SubProducto') ALTER TABLE ProductosFinancieros.ProductoCanalCupo WITH CHECK ADD CONSTRAINT [FK_ProductoCanalCupo_SubProducto] FOREIGN KEY([IdSubProducto]) REFERENCES ProductosFinancieros.SubProducto([IdSubProducto]);
IF NOT EXISTS(SELECT 1 FROM sys.foreign_keys WHERE name=N'FK_ProductoRestriccion_SubProducto') ALTER TABLE ProductosFinancieros.ProductoRestriccion WITH CHECK ADD CONSTRAINT [FK_ProductoRestriccion_SubProducto] FOREIGN KEY([IdSubProducto]) REFERENCES ProductosFinancieros.SubProducto([IdSubProducto]);
IF NOT EXISTS(SELECT 1 FROM sys.foreign_keys WHERE name=N'FK_Comisiones_Canal') ALTER TABLE Transacciones.Comisiones WITH CHECK ADD CONSTRAINT [FK_Comisiones_Canal] FOREIGN KEY([IdCanal]) REFERENCES Canal.Canal([IdCanal]);
IF NOT EXISTS(SELECT 1 FROM sys.foreign_keys WHERE name=N'FK_Transaccion_Canal') ALTER TABLE Transacciones.Transaccion WITH CHECK ADD CONSTRAINT [FK_Transaccion_Canal] FOREIGN KEY([IdCanal]) REFERENCES Canal.Canal([IdCanal]);
IF NOT EXISTS(SELECT 1 FROM sys.foreign_keys WHERE name=N'FK_CanalCupoClienteCustom_Cuenta') ALTER TABLE Canal.CanalCupoClienteCustom WITH CHECK ADD CONSTRAINT [FK_CanalCupoClienteCustom_Cuenta] FOREIGN KEY([IdCuenta]) REFERENCES Cuentas.Cuenta([IdCuenta]);
IF NOT EXISTS(SELECT 1 FROM sys.foreign_keys WHERE name=N'FK_Producto_TipoCredito') ALTER TABLE ProductosFinancieros.Producto WITH CHECK ADD CONSTRAINT [FK_Producto_TipoCredito] FOREIGN KEY([IdTipoCredito]) REFERENCES Credito.TipoCredito([IdTipoCredito]);
IF NOT EXISTS(SELECT 1 FROM sys.foreign_keys WHERE name=N'FK_ProductoCanalCupo_Canal') ALTER TABLE ProductosFinancieros.ProductoCanalCupo WITH CHECK ADD CONSTRAINT [FK_ProductoCanalCupo_Canal] FOREIGN KEY([IdCanal]) REFERENCES Canal.Canal([IdCanal]);
IF NOT EXISTS(SELECT 1 FROM sys.foreign_keys WHERE name=N'FK_CreditoSolicitud_Producto') ALTER TABLE Credito.CreditoSolicitud WITH CHECK ADD CONSTRAINT [FK_CreditoSolicitud_Producto] FOREIGN KEY([IdProducto]) REFERENCES ProductosFinancieros.Producto([IdProducto]);
IF NOT EXISTS(SELECT 1 FROM sys.foreign_keys WHERE name=N'FK_SubProducto_Producto') ALTER TABLE ProductosFinancieros.SubProducto WITH CHECK ADD CONSTRAINT [FK_SubProducto_Producto] FOREIGN KEY([IdProducto]) REFERENCES ProductosFinancieros.Producto([IdProducto]);
IF NOT EXISTS(SELECT 1 FROM sys.foreign_keys WHERE name=N'FK_Cuenta_Producto') ALTER TABLE Cuentas.Cuenta WITH CHECK ADD CONSTRAINT [FK_Cuenta_Producto] FOREIGN KEY([IdProducto]) REFERENCES ProductosFinancieros.Producto([IdProducto]);
