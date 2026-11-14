-- Fixture ficticio: subconjunto de estructura de NewCooperativaDB.sql (sin datos).
-- Solo se carga en una base local nueva con marca BOV_Local_Lab.
CREATE SCHEMA [Boveda];
GO
CREATE SCHEMA [Catalogo];
GO
CREATE SCHEMA [Contabilidad];
GO
CREATE SCHEMA [Organizacion];
GO
CREATE SEQUENCE Organizacion.SeqAgenciaId AS int START WITH 3 INCREMENT BY 1;
GO
CREATE TABLE [Catalogo].[Denominacion](
	[IdDenominacion] [int] IDENTITY(1,1) NOT NULL,
	[TipoPieza] [varchar](10) NOT NULL,
	[Valor] [decimal](10, 2) NOT NULL,
	[Descripcion] [varchar](50) NOT NULL,
	[Estado] [char](1) NOT NULL,
	[FechaRegistro] [datetime2](7) NOT NULL,
 CONSTRAINT [PK_Denominacion] PRIMARY KEY CLUSTERED 
(
	[IdDenominacion] ASC
)WITH (STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY],
 CONSTRAINT [UQ_Denominacion_TipoPieza_Valor] UNIQUE NONCLUSTERED 
(
	[TipoPieza] ASC,
	[Valor] ASC
)WITH (STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
CREATE TABLE [Boveda].[Boveda](
	[IdBoveda] [int] IDENTITY(1,1) NOT NULL,
	[CodigoBoveda] [varchar](10) NOT NULL,
	[TipoBoveda] [varchar](10) NOT NULL,
	[IdAgencia] [char](3) NOT NULL,
	[IdBovedaSuperior] [int] NULL,
	[LimiteMaximo] [decimal](18, 2) NOT NULL,
	[LimiteMinimo] [decimal](18, 2) NOT NULL,
	[SaldoActual] [decimal](18, 2) NOT NULL,
	[Estado] [char](1) NOT NULL,
	[FechaCreacion] [datetime2](7) NOT NULL,
 CONSTRAINT [PK_Boveda] PRIMARY KEY CLUSTERED 
(
	[IdBoveda] ASC
)WITH (STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY],
 CONSTRAINT [UQ_Boveda_Codigo] UNIQUE NONCLUSTERED 
(
	[CodigoBoveda] ASC
)WITH (STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
CREATE TABLE [Boveda].[BovedaDenominacion](
	[IdBovedaDenominacion] [int] IDENTITY(1,1) NOT NULL,
	[IdBoveda] [int] NOT NULL,
	[IdDenominacion] [int] NOT NULL,
	[CantidadActual] [int] NOT NULL,
	[FechaActualizacion] [datetime2](7) NOT NULL,
 CONSTRAINT [PK_BovedaDenominacion] PRIMARY KEY CLUSTERED 
(
	[IdBovedaDenominacion] ASC
)WITH (STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY],
 CONSTRAINT [UQ_BovedaDenominacion] UNIQUE NONCLUSTERED 
(
	[IdBoveda] ASC,
	[IdDenominacion] ASC
)WITH (STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
CREATE TABLE [Contabilidad].[AsientoContable](
	[IdAsientoContable] [int] IDENTITY(1,1) NOT NULL,
	[NumeroAsiento] [varchar](20) NOT NULL,
	[FechaAsiento] [date] NOT NULL,
	[FechaSistema] [datetime2](7) NOT NULL,
	[IdTipoAsiento] [int] NOT NULL,
	[Origen] [varchar](30) NOT NULL,
	[Concepto] [varchar](500) NOT NULL,
	[TotalDebito] [decimal](18, 2) NOT NULL,
	[TotalCredito] [decimal](18, 2) NOT NULL,
	[Estado] [varchar](20) NOT NULL,
	[IdAsientoReversion] [int] NULL,
	[IdUsuarioCreacion] [int] NOT NULL,
	[IdAgencia] [char](3) NOT NULL,
	[IdConceptoContable] [int] NULL,
	[IdFechaContable] [int] NOT NULL,
 CONSTRAINT [PK_AsientoContable] PRIMARY KEY CLUSTERED 
(
	[IdAsientoContable] ASC
)WITH (STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY],
 CONSTRAINT [UQ_AsientoContable_Numero] UNIQUE NONCLUSTERED 
(
	[NumeroAsiento] ASC
)WITH (STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
CREATE TABLE [Contabilidad].[MovimientosContables](
	[IdMovimientoContable] [int] IDENTITY(1,1) NOT NULL,
	[IdCuentaContable] [int] NOT NULL,
	[IdTransaccion] [bigint] NULL,
	[IdAgencia] [char](3) NULL,
	[TipoMovimiento] [varchar](30) NOT NULL,
	[Monto] [decimal](18, 2) NOT NULL,
	[FechaHora] [datetime2](7) NOT NULL,
	[IdAsientoContable] [int] NOT NULL,
 CONSTRAINT [PK_MovimientosContables] PRIMARY KEY CLUSTERED 
(
	[IdMovimientoContable] ASC
)WITH (STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
CREATE TABLE [Contabilidad].[CuentasContables](
	[IdCuentaContable] [int] IDENTITY(1,1) NOT NULL,
	[CodigoCuenta] [varchar](30) NOT NULL,
	[NombreCuenta] [varchar](150) NOT NULL,
	[Naturaleza] [varchar](20) NOT NULL,
	[IdCuentaSuperior] [int] NULL,
	[Saldo] [decimal](18, 2) NOT NULL,
	[Estado] [bit] NOT NULL,
	[FechaCreacion] [datetime2](7) NOT NULL,
	[EsImputable] [bit] NOT NULL,
	[FechaModificacion] [datetime2](7) NULL,
	[CodigoElemento]  AS (CONVERT([char](1),left([CodigoCuenta],(1)))) PERSISTED,
	[TipoCuenta]  AS (CONVERT([varchar](15),case left([CodigoCuenta],(1)) when '1' then 'ACTIVO' when '2' then 'PASIVO' when '3' then 'PATRIMONIO' when '4' then 'GASTO' when '5' then 'INGRESO' when '6' then 'CONTINGENTE' when '7' then 'ORDEN'  end)) PERSISTED,
	[EsCuentaValuacion] [bit] NOT NULL,
 CONSTRAINT [PK_CuentasContables] PRIMARY KEY CLUSTERED 
(
	[IdCuentaContable] ASC
)WITH (STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY],
 CONSTRAINT [UQ_CuentasContables_Codigo] UNIQUE NONCLUSTERED 
(
	[CodigoCuenta] ASC
)WITH (STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
CREATE TABLE [Boveda].[ArqueoBoveda](
	[IdArqueoBoveda] [bigint] IDENTITY(1,1) NOT NULL,
	[IdBoveda] [int] NOT NULL,
	[FechaHoraArqueo] [datetime2](7) NOT NULL,
	[TipoArqueo] [varchar](12) NOT NULL,
	[IdUsuarioArqueador] [int] NOT NULL,
	[IdUsuarioTestigo] [int] NOT NULL,
	[Estado] [varchar](12) NOT NULL,
	[IdMovimientoAjuste] [bigint] NULL,
	[Observaciones] [varchar](500) NULL,
 CONSTRAINT [PK_ArqueoBoveda] PRIMARY KEY CLUSTERED 
(
	[IdArqueoBoveda] ASC
)WITH (STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
CREATE TABLE [Boveda].[ArqueoBovedaDenominacion](
	[IdArqueoBovedaDenominacion] [bigint] IDENTITY(1,1) NOT NULL,
	[IdArqueoBoveda] [bigint] NOT NULL,
	[IdDenominacion] [int] NOT NULL,
	[Cantidad] [int] NOT NULL,
 CONSTRAINT [PK_ArqueoBovedaDenominacion] PRIMARY KEY CLUSTERED 
(
	[IdArqueoBovedaDenominacion] ASC
)WITH (STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY],
 CONSTRAINT [UQ_ArqueoBovedaDenominacion] UNIQUE NONCLUSTERED 
(
	[IdArqueoBoveda] ASC,
	[IdDenominacion] ASC
)WITH (STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
CREATE TABLE [Boveda].[MovimientoBoveda](
	[IdMovimiento] [bigint] IDENTITY(1,1) NOT NULL,
	[IdBoveda] [int] NOT NULL,
	[IdBovedaContraparte] [int] NULL,
	[TipoMovimiento] [varchar](20) NOT NULL,
	[Naturaleza] [char](1) NOT NULL,
	[Monto] [decimal](18, 2) NOT NULL,
	[SaldoAnterior] [decimal](18, 2) NOT NULL,
	[SaldoPosterior] [decimal](18, 2) NOT NULL,
	[AutorizadoPor] [int] NOT NULL,
	[IdUsuarioMovimiento] [int] NOT NULL,
	[Observaciones] [varchar](300) NULL,
	[FechaMovimiento] [datetime2](7) NOT NULL,
	[IdMovimientoRelacionado] [bigint] NULL,
	[IdFechaContable] [int] NOT NULL,
 CONSTRAINT [PK_MovimientoBoveda] PRIMARY KEY CLUSTERED 
(
	[IdMovimiento] ASC
)WITH (STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY],
 CONSTRAINT [UQ_MovimientoBoveda_Movimiento_Boveda_Monto] UNIQUE NONCLUSTERED 
(
	[IdMovimiento] ASC,
	[IdBoveda] ASC,
	[Monto] ASC
)WITH (STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
CREATE TABLE [Boveda].[MovimientoBovedaDenominacion](
	[IdMovBovedaDenom] [int] IDENTITY(1,1) NOT NULL,
	[IdMovimiento] [bigint] NOT NULL,
	[IdDenominacion] [int] NOT NULL,
	[Cantidad] [int] NOT NULL,
 CONSTRAINT [PK_MovimientoBovedaDenominacion] PRIMARY KEY CLUSTERED 
(
	[IdMovBovedaDenom] ASC
)WITH (STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY],
 CONSTRAINT [UQ_MovBovedaDenom] UNIQUE NONCLUSTERED 
(
	[IdMovimiento] ASC,
	[IdDenominacion] ASC
)WITH (STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
CREATE TABLE [Contabilidad].[FechaContable](
	[IdFechaContable] [int] IDENTITY(1,1) NOT NULL,
	[Fecha] [date] NOT NULL,
	[Anio]  AS (datepart(year,[Fecha])) PERSISTED,
	[Mes]  AS (datepart(month,[Fecha])) PERSISTED,
	[Dia]  AS (datepart(day,[Fecha])) PERSISTED,
	[NumeroDiaSemana] [tinyint] NOT NULL,
	[NombreDiaSemana] [varchar](15) NOT NULL,
	[EsFeriado] [bit] NOT NULL,
	[IdFeriado] [int] NULL,
	[FechaRegistro] [datetime2](7) NOT NULL,
	[HoraCorte] [time](0) NOT NULL,
	[EsFinDeSemana]  AS (CONVERT([bit],case when [NumeroDiaSemana]=(7) OR [NumeroDiaSemana]=(6) then (1) else (0) end)) PERSISTED,
	[EsDiaContable]  AS (CONVERT([bit],case when NOT ([NumeroDiaSemana]=(7) OR [NumeroDiaSemana]=(6)) AND [EsFeriado]=(0) then (1) else (0) end)) PERSISTED,
 CONSTRAINT [PK_FechaContable] PRIMARY KEY CLUSTERED 
(
	[IdFechaContable] ASC
)WITH (STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY],
 CONSTRAINT [UQ_FechaContable] UNIQUE NONCLUSTERED 
(
	[Fecha] ASC
)WITH (STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
CREATE TABLE [Contabilidad].[PeriodoContable](
	[IdPeriodoContable] [int] IDENTITY(1,1) NOT NULL,
	[Anio] [smallint] NOT NULL,
	[Mes] [tinyint] NOT NULL,
	[Estado] [varchar](10) NOT NULL,
	[FechaCierre] [datetime2](7) NULL,
	[CerradoPor] [int] NULL,
 CONSTRAINT [PK_PeriodoContable] PRIMARY KEY CLUSTERED 
(
	[IdPeriodoContable] ASC
)WITH (STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY],
 CONSTRAINT [UQ_PeriodoContable_AnioMes] UNIQUE NONCLUSTERED 
(
	[Anio] ASC,
	[Mes] ASC
)WITH (STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
CREATE TABLE [Contabilidad].[TiposAsiento](
	[IdTipoAsiento] [int] IDENTITY(1,1) NOT NULL,
	[Codigo] [varchar](30) NOT NULL,
	[Nombre] [varchar](80) NOT NULL,
	[Descripcion] [varchar](250) NOT NULL,
	[EsManual] [bit] NOT NULL,
	[Estado] [char](1) NOT NULL,
 CONSTRAINT [PK_TiposAsiento] PRIMARY KEY CLUSTERED 
(
	[IdTipoAsiento] ASC
)WITH (STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY],
 CONSTRAINT [UQ_TiposAsiento_Codigo] UNIQUE NONCLUSTERED 
(
	[Codigo] ASC
)WITH (STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
CREATE TABLE [Organizacion].[Agencia](
	[IdAgencia] [char](3) NOT NULL,
	[Codigo] [varchar](10) NOT NULL,
	[TipoAgencia] [varchar](10) NOT NULL,
	[Estado] [char](1) NOT NULL,
	[Telefono] [varchar](15) NULL,
	[Direccion] [varchar](250) NULL,
	[FechaCreacion] [datetime2](7) NOT NULL,
	[IdCiudad] [int] NOT NULL,
	[KeyAgencia] [varchar](64) NULL,
	[IdEntidad] [tinyint] NOT NULL,
 CONSTRAINT [PK_Agencia] PRIMARY KEY CLUSTERED 
(
	[IdAgencia] ASC
)WITH (STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY],
 CONSTRAINT [UQ_Agencia_Codigo] UNIQUE NONCLUSTERED 
(
	[Codigo] ASC
)WITH (STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
ALTER TABLE [Boveda].[ArqueoBoveda] ADD  CONSTRAINT [DF_ArqueoBoveda_FechaHoraArqueo]  DEFAULT (CONVERT([datetime2],(sysdatetimeoffset() AT TIME ZONE 'SA Pacific Standard Time'))) FOR [FechaHoraArqueo]
GO
ALTER TABLE [Boveda].[ArqueoBoveda] ADD  CONSTRAINT [DF_ArqueoBoveda_Estado]  DEFAULT ('REGISTRADO') FOR [Estado]
GO
ALTER TABLE [Boveda].[Boveda] ADD  DEFAULT ((0)) FOR [SaldoActual]
GO
ALTER TABLE [Boveda].[Boveda] ADD  DEFAULT (('A') collate SQL_Latin1_General_CP1_CI_AS) FOR [Estado]
GO
ALTER TABLE [Boveda].[Boveda] ADD  CONSTRAINT [DF_Boveda_FechaCreacion]  DEFAULT (CONVERT([datetime2],(sysdatetimeoffset() AT TIME ZONE 'SA Pacific Standard Time'))) FOR [FechaCreacion]
GO
ALTER TABLE [Boveda].[BovedaDenominacion] ADD  CONSTRAINT [DF_BovedaDenominacion_FechaActualizacion]  DEFAULT (CONVERT([datetime2],(sysdatetimeoffset() AT TIME ZONE 'SA Pacific Standard Time'))) FOR [FechaActualizacion]
GO
ALTER TABLE [Boveda].[MovimientoBoveda] ADD  CONSTRAINT [DF_MovimientoBoveda_FechaMovimiento]  DEFAULT (CONVERT([datetime2],(sysdatetimeoffset() AT TIME ZONE 'SA Pacific Standard Time'))) FOR [FechaMovimiento]
GO
ALTER TABLE [Catalogo].[Denominacion] ADD  DEFAULT (('A') collate SQL_Latin1_General_CP1_CI_AS) FOR [Estado]
GO
ALTER TABLE [Catalogo].[Denominacion] ADD  CONSTRAINT [DF_Denominacion_FechaRegistro]  DEFAULT (CONVERT([datetime2],(sysdatetimeoffset() AT TIME ZONE 'SA Pacific Standard Time'))) FOR [FechaRegistro]
GO
ALTER TABLE [Contabilidad].[AsientoContable] ADD  CONSTRAINT [DF_AsientoContable_FechaSistema]  DEFAULT (CONVERT([datetime2],(sysdatetimeoffset() AT TIME ZONE 'SA Pacific Standard Time'))) FOR [FechaSistema]
GO
ALTER TABLE [Contabilidad].[CuentasContables] ADD  DEFAULT ((0)) FOR [Saldo]
GO
ALTER TABLE [Contabilidad].[CuentasContables] ADD  DEFAULT ((1)) FOR [Estado]
GO
ALTER TABLE [Contabilidad].[CuentasContables] ADD  CONSTRAINT [DF_CuentasContables_FechaCreacion]  DEFAULT (CONVERT([datetime2],(sysdatetimeoffset() AT TIME ZONE 'SA Pacific Standard Time'))) FOR [FechaCreacion]
GO
ALTER TABLE [Contabilidad].[CuentasContables] ADD  DEFAULT ((1)) FOR [EsImputable]
GO
ALTER TABLE [Contabilidad].[CuentasContables] ADD  CONSTRAINT [DF_CuentasContables_EsCuentaValuacion]  DEFAULT ((0)) FOR [EsCuentaValuacion]
GO
ALTER TABLE [Contabilidad].[FechaContable] ADD  DEFAULT ((0)) FOR [EsFeriado]
GO
ALTER TABLE [Contabilidad].[FechaContable] ADD  CONSTRAINT [DF_FechaContable_FechaRegistro]  DEFAULT (CONVERT([datetime2],(sysdatetimeoffset() AT TIME ZONE 'SA Pacific Standard Time'))) FOR [FechaRegistro]
GO
ALTER TABLE [Contabilidad].[FechaContable] ADD  CONSTRAINT [DF_FechaContable_HoraCorte]  DEFAULT ('19:00:00') FOR [HoraCorte]
GO
ALTER TABLE [Contabilidad].[MovimientosContables] ADD  CONSTRAINT [DF_MovimientosContables_FechaHora]  DEFAULT (CONVERT([datetime2],(sysdatetimeoffset() AT TIME ZONE 'SA Pacific Standard Time'))) FOR [FechaHora]
GO
ALTER TABLE [Contabilidad].[PeriodoContable] ADD  CONSTRAINT [DF_PeriodoContable_Estado]  DEFAULT ('ABIERTO') FOR [Estado]
GO
ALTER TABLE [Contabilidad].[TiposAsiento] ADD  DEFAULT ((0)) FOR [EsManual]
GO
ALTER TABLE [Contabilidad].[TiposAsiento] ADD  DEFAULT (('A') collate SQL_Latin1_General_CP1_CI_AS) FOR [Estado]
GO
ALTER TABLE [Organizacion].[Agencia] ADD  CONSTRAINT [DF_Agencia_IdAgencia]  DEFAULT (right('000'+CONVERT([varchar](10),NEXT VALUE FOR [Organizacion].[SeqAgenciaId]),(3))) FOR [IdAgencia]
GO
ALTER TABLE [Organizacion].[Agencia] ADD  DEFAULT (('A') collate SQL_Latin1_General_CP1_CI_AS) FOR [Estado]
GO
ALTER TABLE [Organizacion].[Agencia] ADD  CONSTRAINT [DF_Agencia_FechaCreacion]  DEFAULT (CONVERT([datetime2],(sysdatetimeoffset() AT TIME ZONE 'SA Pacific Standard Time'))) FOR [FechaCreacion]
GO
ALTER TABLE [Organizacion].[Agencia] ADD  CONSTRAINT [DF_Agencia_IdEntidad]  DEFAULT ((1)) FOR [IdEntidad]
GO
ALTER TABLE [Boveda].[ArqueoBoveda]  WITH CHECK ADD  CONSTRAINT [FK_ArqueoBoveda_Boveda] FOREIGN KEY([IdBoveda])
REFERENCES [Boveda].[Boveda] ([IdBoveda])
GO
ALTER TABLE [Boveda].[ArqueoBoveda] CHECK CONSTRAINT [FK_ArqueoBoveda_Boveda]
GO
ALTER TABLE [Boveda].[ArqueoBoveda]  WITH CHECK ADD  CONSTRAINT [FK_ArqueoBoveda_MovimientoAjuste] FOREIGN KEY([IdMovimientoAjuste])
REFERENCES [Boveda].[MovimientoBoveda] ([IdMovimiento])
GO
ALTER TABLE [Boveda].[ArqueoBoveda] CHECK CONSTRAINT [FK_ArqueoBoveda_MovimientoAjuste]
GO
ALTER TABLE [Boveda].[ArqueoBovedaDenominacion]  WITH CHECK ADD  CONSTRAINT [FK_ArqueoBovedaDenominacion_Arqueo] FOREIGN KEY([IdArqueoBoveda])
REFERENCES [Boveda].[ArqueoBoveda] ([IdArqueoBoveda])
GO
ALTER TABLE [Boveda].[ArqueoBovedaDenominacion] CHECK CONSTRAINT [FK_ArqueoBovedaDenominacion_Arqueo]
GO
ALTER TABLE [Boveda].[ArqueoBovedaDenominacion]  WITH CHECK ADD  CONSTRAINT [FK_ArqueoBovedaDenominacion_Denominacion] FOREIGN KEY([IdDenominacion])
REFERENCES [Catalogo].[Denominacion] ([IdDenominacion])
GO
ALTER TABLE [Boveda].[ArqueoBovedaDenominacion] CHECK CONSTRAINT [FK_ArqueoBovedaDenominacion_Denominacion]
GO
ALTER TABLE [Boveda].[Boveda]  WITH CHECK ADD  CONSTRAINT [FK_Boveda_Agencia] FOREIGN KEY([IdAgencia])
REFERENCES [Organizacion].[Agencia] ([IdAgencia])
GO
ALTER TABLE [Boveda].[Boveda] CHECK CONSTRAINT [FK_Boveda_Agencia]
GO
ALTER TABLE [Boveda].[Boveda]  WITH CHECK ADD  CONSTRAINT [FK_Boveda_Superior] FOREIGN KEY([IdBovedaSuperior])
REFERENCES [Boveda].[Boveda] ([IdBoveda])
GO
ALTER TABLE [Boveda].[Boveda] CHECK CONSTRAINT [FK_Boveda_Superior]
GO
ALTER TABLE [Boveda].[BovedaDenominacion]  WITH CHECK ADD  CONSTRAINT [FK_BovedaDenominacion_Boveda] FOREIGN KEY([IdBoveda])
REFERENCES [Boveda].[Boveda] ([IdBoveda])
GO
ALTER TABLE [Boveda].[BovedaDenominacion] CHECK CONSTRAINT [FK_BovedaDenominacion_Boveda]
GO
ALTER TABLE [Boveda].[BovedaDenominacion]  WITH CHECK ADD  CONSTRAINT [FK_BovedaDenominacion_Denominacion] FOREIGN KEY([IdDenominacion])
REFERENCES [Catalogo].[Denominacion] ([IdDenominacion])
GO
ALTER TABLE [Boveda].[BovedaDenominacion] CHECK CONSTRAINT [FK_BovedaDenominacion_Denominacion]
GO
ALTER TABLE [Boveda].[MovimientoBoveda]  WITH CHECK ADD  CONSTRAINT [FK_MovimientoBoveda_Boveda] FOREIGN KEY([IdBoveda])
REFERENCES [Boveda].[Boveda] ([IdBoveda])
GO
ALTER TABLE [Boveda].[MovimientoBoveda] CHECK CONSTRAINT [FK_MovimientoBoveda_Boveda]
GO
ALTER TABLE [Boveda].[MovimientoBoveda]  WITH CHECK ADD  CONSTRAINT [FK_MovimientoBoveda_BovedaContraparte] FOREIGN KEY([IdBovedaContraparte])
REFERENCES [Boveda].[Boveda] ([IdBoveda])
GO
ALTER TABLE [Boveda].[MovimientoBoveda] CHECK CONSTRAINT [FK_MovimientoBoveda_BovedaContraparte]
GO
ALTER TABLE [Boveda].[MovimientoBoveda]  WITH CHECK ADD  CONSTRAINT [FK_MovimientoBoveda_FechaContable] FOREIGN KEY([IdFechaContable])
REFERENCES [Contabilidad].[FechaContable] ([IdFechaContable])
GO
ALTER TABLE [Boveda].[MovimientoBoveda] CHECK CONSTRAINT [FK_MovimientoBoveda_FechaContable]
GO
ALTER TABLE [Boveda].[MovimientoBoveda]  WITH CHECK ADD  CONSTRAINT [FK_MovimientoBoveda_Relacionado] FOREIGN KEY([IdMovimientoRelacionado])
REFERENCES [Boveda].[MovimientoBoveda] ([IdMovimiento])
GO
ALTER TABLE [Boveda].[MovimientoBoveda] CHECK CONSTRAINT [FK_MovimientoBoveda_Relacionado]
GO
ALTER TABLE [Boveda].[MovimientoBovedaDenominacion]  WITH CHECK ADD  CONSTRAINT [FK_MovBovedaDenom_Denominacion] FOREIGN KEY([IdDenominacion])
REFERENCES [Catalogo].[Denominacion] ([IdDenominacion])
GO
ALTER TABLE [Boveda].[MovimientoBovedaDenominacion] CHECK CONSTRAINT [FK_MovBovedaDenom_Denominacion]
GO
ALTER TABLE [Boveda].[MovimientoBovedaDenominacion]  WITH CHECK ADD  CONSTRAINT [FK_MovBovedaDenom_Movimiento] FOREIGN KEY([IdMovimiento])
REFERENCES [Boveda].[MovimientoBoveda] ([IdMovimiento])
GO
ALTER TABLE [Boveda].[MovimientoBovedaDenominacion] CHECK CONSTRAINT [FK_MovBovedaDenom_Movimiento]
GO
ALTER TABLE [Contabilidad].[AsientoContable]  WITH CHECK ADD  CONSTRAINT [FK_AsientoContable_Agencia] FOREIGN KEY([IdAgencia])
REFERENCES [Organizacion].[Agencia] ([IdAgencia])
GO
ALTER TABLE [Contabilidad].[AsientoContable] CHECK CONSTRAINT [FK_AsientoContable_Agencia]
GO
ALTER TABLE [Contabilidad].[AsientoContable]  WITH CHECK ADD  CONSTRAINT [FK_AsientoContable_FechaContable] FOREIGN KEY([IdFechaContable])
REFERENCES [Contabilidad].[FechaContable] ([IdFechaContable])
GO
ALTER TABLE [Contabilidad].[AsientoContable] CHECK CONSTRAINT [FK_AsientoContable_FechaContable]
GO
ALTER TABLE [Contabilidad].[AsientoContable]  WITH CHECK ADD  CONSTRAINT [FK_AsientoContable_Reversion] FOREIGN KEY([IdAsientoReversion])
REFERENCES [Contabilidad].[AsientoContable] ([IdAsientoContable])
GO
ALTER TABLE [Contabilidad].[AsientoContable] CHECK CONSTRAINT [FK_AsientoContable_Reversion]
GO
ALTER TABLE [Contabilidad].[AsientoContable]  WITH CHECK ADD  CONSTRAINT [FK_AsientoContable_Tipo] FOREIGN KEY([IdTipoAsiento])
REFERENCES [Contabilidad].[TiposAsiento] ([IdTipoAsiento])
GO
ALTER TABLE [Contabilidad].[AsientoContable] CHECK CONSTRAINT [FK_AsientoContable_Tipo]
GO
ALTER TABLE [Contabilidad].[CuentasContables]  WITH CHECK ADD  CONSTRAINT [FK_CuentasContables_Superior] FOREIGN KEY([IdCuentaSuperior])
REFERENCES [Contabilidad].[CuentasContables] ([IdCuentaContable])
GO
ALTER TABLE [Contabilidad].[CuentasContables] CHECK CONSTRAINT [FK_CuentasContables_Superior]
GO
ALTER TABLE [Contabilidad].[MovimientosContables]  WITH CHECK ADD  CONSTRAINT [FK_MovimientosContables_Agencia] FOREIGN KEY([IdAgencia])
REFERENCES [Organizacion].[Agencia] ([IdAgencia])
GO
ALTER TABLE [Contabilidad].[MovimientosContables] CHECK CONSTRAINT [FK_MovimientosContables_Agencia]
GO
ALTER TABLE [Contabilidad].[MovimientosContables]  WITH CHECK ADD  CONSTRAINT [FK_MovimientosContables_Asiento] FOREIGN KEY([IdAsientoContable])
REFERENCES [Contabilidad].[AsientoContable] ([IdAsientoContable])
GO
ALTER TABLE [Contabilidad].[MovimientosContables] CHECK CONSTRAINT [FK_MovimientosContables_Asiento]
GO
ALTER TABLE [Contabilidad].[MovimientosContables]  WITH CHECK ADD  CONSTRAINT [FK_MovimientosContables_Cuenta] FOREIGN KEY([IdCuentaContable])
REFERENCES [Contabilidad].[CuentasContables] ([IdCuentaContable])
GO
ALTER TABLE [Contabilidad].[MovimientosContables] CHECK CONSTRAINT [FK_MovimientosContables_Cuenta]
GO
ALTER TABLE [Boveda].[ArqueoBoveda]  WITH CHECK ADD  CONSTRAINT [CK_ArqueoBoveda_Estado] CHECK  (([Estado]='ANULADO' OR [Estado]='APROBADO' OR [Estado]='REGISTRADO'))
GO
ALTER TABLE [Boveda].[ArqueoBoveda] CHECK CONSTRAINT [CK_ArqueoBoveda_Estado]
GO
ALTER TABLE [Boveda].[ArqueoBoveda]  WITH CHECK ADD  CONSTRAINT [CK_ArqueoBoveda_Tipo] CHECK  (([TipoArqueo]='Sorpresivo' OR [TipoArqueo]='Programado'))
GO
ALTER TABLE [Boveda].[ArqueoBoveda] CHECK CONSTRAINT [CK_ArqueoBoveda_Tipo]
GO
ALTER TABLE [Boveda].[ArqueoBoveda]  WITH CHECK ADD  CONSTRAINT [CK_ArqueoBoveda_Usuarios] CHECK  (([IdUsuarioArqueador]<>[IdUsuarioTestigo]))
GO
ALTER TABLE [Boveda].[ArqueoBoveda] CHECK CONSTRAINT [CK_ArqueoBoveda_Usuarios]
GO
ALTER TABLE [Boveda].[ArqueoBovedaDenominacion]  WITH CHECK ADD  CONSTRAINT [CK_ArqueoBovedaDenominacion_Cantidad] CHECK  (([Cantidad]>=(0)))
GO
ALTER TABLE [Boveda].[ArqueoBovedaDenominacion] CHECK CONSTRAINT [CK_ArqueoBovedaDenominacion_Cantidad]
GO
ALTER TABLE [Boveda].[Boveda]  WITH CHECK ADD  CONSTRAINT [CK_Boveda_Estado] CHECK  (([Estado]='I' OR [Estado]='A'))
GO
ALTER TABLE [Boveda].[Boveda] CHECK CONSTRAINT [CK_Boveda_Estado]
GO
ALTER TABLE [Boveda].[Boveda]  WITH CHECK ADD  CONSTRAINT [CK_Boveda_EstadoSaldo] CHECK  (([Estado]='A' OR [SaldoActual]=(0)))
GO
ALTER TABLE [Boveda].[Boveda] CHECK CONSTRAINT [CK_Boveda_EstadoSaldo]
GO
ALTER TABLE [Boveda].[Boveda]  WITH CHECK ADD  CONSTRAINT [CK_Boveda_Jerarquia] CHECK  (([TipoBoveda]='General' AND [IdBovedaSuperior] IS NULL OR [TipoBoveda]<>'General' AND [IdBovedaSuperior] IS NOT NULL))
GO
ALTER TABLE [Boveda].[Boveda] CHECK CONSTRAINT [CK_Boveda_Jerarquia]
GO
ALTER TABLE [Boveda].[Boveda]  WITH CHECK ADD  CONSTRAINT [CK_Boveda_Limite] CHECK  (([LimiteMaximo]>(0)))
GO
ALTER TABLE [Boveda].[Boveda] CHECK CONSTRAINT [CK_Boveda_Limite]
GO
ALTER TABLE [Boveda].[Boveda]  WITH CHECK ADD  CONSTRAINT [CK_Boveda_LimiteMinimo] CHECK  (([LimiteMinimo]>=(0) AND [LimiteMinimo]<[LimiteMaximo]))
GO
ALTER TABLE [Boveda].[Boveda] CHECK CONSTRAINT [CK_Boveda_LimiteMinimo]
GO
ALTER TABLE [Boveda].[Boveda]  WITH CHECK ADD  CONSTRAINT [CK_Boveda_Saldo] CHECK  (([SaldoActual]>=(0)))
GO
ALTER TABLE [Boveda].[Boveda] CHECK CONSTRAINT [CK_Boveda_Saldo]
GO
ALTER TABLE [Boveda].[Boveda]  WITH CHECK ADD  CONSTRAINT [CK_Boveda_Tipo] CHECK  (([TipoBoveda]='General' OR [TipoBoveda]='Mayor' OR [TipoBoveda]='Menor'))
GO
ALTER TABLE [Boveda].[Boveda] CHECK CONSTRAINT [CK_Boveda_Tipo]
GO
ALTER TABLE [Boveda].[BovedaDenominacion]  WITH CHECK ADD  CONSTRAINT [CK_BovedaDenominacion_Cantidad] CHECK  (([CantidadActual]>=(0)))
GO
ALTER TABLE [Boveda].[BovedaDenominacion] CHECK CONSTRAINT [CK_BovedaDenominacion_Cantidad]
GO
ALTER TABLE [Boveda].[MovimientoBoveda]  WITH CHECK ADD  CONSTRAINT [CK_MovimientoBoveda_Cuadre] CHECK  (([Naturaleza]='I' AND [SaldoPosterior]=([SaldoAnterior]+[Monto]) OR [Naturaleza]='E' AND [SaldoPosterior]=([SaldoAnterior]-[Monto])))
GO
ALTER TABLE [Boveda].[MovimientoBoveda] CHECK CONSTRAINT [CK_MovimientoBoveda_Cuadre]
GO
ALTER TABLE [Boveda].[MovimientoBoveda]  WITH CHECK ADD  CONSTRAINT [CK_MovimientoBoveda_Monto] CHECK  (([Monto]>(0)))
GO
ALTER TABLE [Boveda].[MovimientoBoveda] CHECK CONSTRAINT [CK_MovimientoBoveda_Monto]
GO
ALTER TABLE [Boveda].[MovimientoBoveda]  WITH CHECK ADD  CONSTRAINT [CK_MovimientoBoveda_Naturaleza] CHECK  (([Naturaleza]='I' OR [Naturaleza]='E'))
GO
ALTER TABLE [Boveda].[MovimientoBoveda] CHECK CONSTRAINT [CK_MovimientoBoveda_Naturaleza]
GO
ALTER TABLE [Boveda].[MovimientoBoveda]  WITH CHECK ADD  CONSTRAINT [CK_MovimientoBoveda_Relacionado] CHECK  (([IdMovimientoRelacionado] IS NULL OR [IdMovimientoRelacionado]<>[IdMovimiento]))
GO
ALTER TABLE [Boveda].[MovimientoBoveda] CHECK CONSTRAINT [CK_MovimientoBoveda_Relacionado]
GO
ALTER TABLE [Boveda].[MovimientoBoveda]  WITH CHECK ADD  CONSTRAINT [CK_MovimientoBoveda_Saldos] CHECK  (([SaldoAnterior]>=(0) AND [SaldoPosterior]>=(0)))
GO
ALTER TABLE [Boveda].[MovimientoBoveda] CHECK CONSTRAINT [CK_MovimientoBoveda_Saldos]
GO
ALTER TABLE [Boveda].[MovimientoBoveda]  WITH CHECK ADD  CONSTRAINT [CK_MovimientoBoveda_Tipo] CHECK  (([TipoMovimiento]='AjusteFaltante' OR [TipoMovimiento]='AjusteSobrante' OR [TipoMovimiento]='Traslado' OR [TipoMovimiento]='RemanenteATM' OR [TipoMovimiento]='AbastecimientoATM' OR [TipoMovimiento]='DevolucionCaja' OR [TipoMovimiento]='DotacionCaja' OR [TipoMovimiento]='EnvioExcedente'))
GO
ALTER TABLE [Boveda].[MovimientoBoveda] CHECK CONSTRAINT [CK_MovimientoBoveda_Tipo]
GO
ALTER TABLE [Boveda].[MovimientoBoveda]  WITH CHECK ADD  CONSTRAINT [CK_MovimientoBoveda_TipoNaturaleza] CHECK  ((([TipoMovimiento]='AjusteFaltante' OR [TipoMovimiento]='EnvioExcedente' OR [TipoMovimiento]='AbastecimientoATM' OR [TipoMovimiento]='DotacionCaja') AND [Naturaleza]='E' OR ([TipoMovimiento]='AjusteSobrante' OR [TipoMovimiento]='RemanenteATM' OR [TipoMovimiento]='DevolucionCaja') AND [Naturaleza]='I' OR [TipoMovimiento]='Traslado'))
GO
ALTER TABLE [Boveda].[MovimientoBoveda] CHECK CONSTRAINT [CK_MovimientoBoveda_TipoNaturaleza]
GO
ALTER TABLE [Boveda].[MovimientoBoveda]  WITH CHECK ADD  CONSTRAINT [CK_MovimientoBoveda_Traslado] CHECK  (([TipoMovimiento]<>'Traslado' OR [IdBovedaContraparte] IS NOT NULL AND [IdBovedaContraparte]<>[IdBoveda] AND ([Naturaleza]='E' OR [IdMovimientoRelacionado] IS NOT NULL)))
GO
ALTER TABLE [Boveda].[MovimientoBoveda] CHECK CONSTRAINT [CK_MovimientoBoveda_Traslado]
GO
ALTER TABLE [Boveda].[MovimientoBoveda]  WITH CHECK ADD  CONSTRAINT [CK_MovimientoBoveda_UsuariosDistintos] CHECK  (([AutorizadoPor]<>[IdUsuarioMovimiento]))
GO
ALTER TABLE [Boveda].[MovimientoBoveda] CHECK CONSTRAINT [CK_MovimientoBoveda_UsuariosDistintos]
GO
ALTER TABLE [Boveda].[MovimientoBovedaDenominacion]  WITH CHECK ADD  CONSTRAINT [CK_MovBovedaDenom_Cantidad] CHECK  (([Cantidad]>(0)))
GO
ALTER TABLE [Boveda].[MovimientoBovedaDenominacion] CHECK CONSTRAINT [CK_MovBovedaDenom_Cantidad]
GO
ALTER TABLE [Catalogo].[Denominacion]  WITH CHECK ADD  CONSTRAINT [CK_Denominacion_Estado] CHECK  (([Estado]='I' OR [Estado]='A'))
GO
ALTER TABLE [Catalogo].[Denominacion] CHECK CONSTRAINT [CK_Denominacion_Estado]
GO
ALTER TABLE [Catalogo].[Denominacion]  WITH CHECK ADD  CONSTRAINT [CK_Denominacion_TipoPieza] CHECK  (([TipoPieza]='Billete' OR [TipoPieza]='Moneda'))
GO
ALTER TABLE [Catalogo].[Denominacion] CHECK CONSTRAINT [CK_Denominacion_TipoPieza]
GO
ALTER TABLE [Catalogo].[Denominacion]  WITH CHECK ADD  CONSTRAINT [CK_Denominacion_Valor] CHECK  (([Valor]>(0)))
GO
ALTER TABLE [Catalogo].[Denominacion] CHECK CONSTRAINT [CK_Denominacion_Valor]
GO
ALTER TABLE [Contabilidad].[AsientoContable]  WITH CHECK ADD  CONSTRAINT [CK_AsientoContable_Cuadre] CHECK  (([TotalDebito]=[TotalCredito]))
GO
ALTER TABLE [Contabilidad].[AsientoContable] CHECK CONSTRAINT [CK_AsientoContable_Cuadre]
GO
ALTER TABLE [Contabilidad].[AsientoContable]  WITH CHECK ADD  CONSTRAINT [CK_AsientoContable_Estado] CHECK  (([Estado]='REVERSADO' OR [Estado]='ANULADO' OR [Estado]='CONTABILIZADO' OR [Estado]='PENDIENTE_APROBACION' OR [Estado]='BORRADOR'))
GO
ALTER TABLE [Contabilidad].[AsientoContable] CHECK CONSTRAINT [CK_AsientoContable_Estado]
GO
ALTER TABLE [Contabilidad].[AsientoContable]  WITH CHECK ADD  CONSTRAINT [CK_AsientoContable_Origen] CHECK  (([Origen]='AJUSTE' OR [Origen]='CIERRE' OR [Origen]='MANUAL' OR [Origen]='NOMINA' OR [Origen]='TRANSACCIONES' OR [Origen]='TARJETA' OR [Origen]='CREDITO' OR [Origen]='CUENTAS' OR [Origen]='BOVEDA' OR [Origen]='ATM' OR [Origen]='CAJA'))
GO
ALTER TABLE [Contabilidad].[AsientoContable] CHECK CONSTRAINT [CK_AsientoContable_Origen]
GO
ALTER TABLE [Contabilidad].[AsientoContable]  WITH CHECK ADD  CONSTRAINT [CK_AsientoContable_Reversion] CHECK  (([IdAsientoReversion] IS NULL OR [IdAsientoReversion]<>[IdAsientoContable]))
GO
ALTER TABLE [Contabilidad].[AsientoContable] CHECK CONSTRAINT [CK_AsientoContable_Reversion]
GO
ALTER TABLE [Contabilidad].[AsientoContable]  WITH CHECK ADD  CONSTRAINT [CK_AsientoContable_TotalCredito] CHECK  (([TotalCredito]>=(0)))
GO
ALTER TABLE [Contabilidad].[AsientoContable] CHECK CONSTRAINT [CK_AsientoContable_TotalCredito]
GO
ALTER TABLE [Contabilidad].[AsientoContable]  WITH CHECK ADD  CONSTRAINT [CK_AsientoContable_TotalDebito] CHECK  (([TotalDebito]>=(0)))
GO
ALTER TABLE [Contabilidad].[AsientoContable] CHECK CONSTRAINT [CK_AsientoContable_TotalDebito]
GO
ALTER TABLE [Contabilidad].[CuentasContables]  WITH CHECK ADD  CONSTRAINT [CK_CuentasContables_CodigoNumerico] CHECK  ((len([CodigoCuenta])>=(1) AND NOT [CodigoCuenta] like '%[^0-9]%'))
GO
ALTER TABLE [Contabilidad].[CuentasContables] CHECK CONSTRAINT [CK_CuentasContables_CodigoNumerico]
GO
ALTER TABLE [Contabilidad].[CuentasContables]  WITH CHECK ADD  CONSTRAINT [CK_CuentasContables_InactivaSinSaldo] CHECK  (([Estado]=(1) OR [Saldo]=(0)))
GO
ALTER TABLE [Contabilidad].[CuentasContables] CHECK CONSTRAINT [CK_CuentasContables_InactivaSinSaldo]
GO
ALTER TABLE [Contabilidad].[CuentasContables]  WITH CHECK ADD  CONSTRAINT [CK_CuentasContables_Naturaleza] CHECK  (([Naturaleza]='ACREEDORA' OR [Naturaleza]='DEUDORA'))
GO
ALTER TABLE [Contabilidad].[CuentasContables] CHECK CONSTRAINT [CK_CuentasContables_Naturaleza]
GO
ALTER TABLE [Contabilidad].[FechaContable]  WITH CHECK ADD  CONSTRAINT [CK_FechaContable_DiaSemana] CHECK  (([NumeroDiaSemana]>=(1) AND [NumeroDiaSemana]<=(7) AND [NumeroDiaSemana]=(datediff(day,CONVERT([date],'19000101',(112)),[Fecha])%(7)+(1)) AND [NombreDiaSemana]=case [NumeroDiaSemana] when (1) then N'Lunes' when (2) then N'Martes' when (3) then N'Miércoles' when (4) then N'Jueves' when (5) then N'Viernes' when (6) then N'Sábado' when (7) then N'Domingo'  end))
GO
ALTER TABLE [Contabilidad].[FechaContable] CHECK CONSTRAINT [CK_FechaContable_DiaSemana]
GO
ALTER TABLE [Contabilidad].[MovimientosContables]  WITH CHECK ADD  CONSTRAINT [CK_MovimientosContables_Monto] CHECK  (([Monto]>(0)))
GO
ALTER TABLE [Contabilidad].[MovimientosContables] CHECK CONSTRAINT [CK_MovimientosContables_Monto]
GO
ALTER TABLE [Contabilidad].[MovimientosContables]  WITH CHECK ADD  CONSTRAINT [CK_MovimientosContables_TipoMovimiento] CHECK  (([TipoMovimiento]='DEBITO' OR [TipoMovimiento]='CREDITO'))
GO
ALTER TABLE [Contabilidad].[MovimientosContables] CHECK CONSTRAINT [CK_MovimientosContables_TipoMovimiento]
GO
ALTER TABLE [Contabilidad].[PeriodoContable]  WITH CHECK ADD  CONSTRAINT [CK_PeriodoContable_Estado] CHECK  (([Estado]='ABIERTO' AND [FechaCierre] IS NULL AND [CerradoPor] IS NULL OR [Estado]='CERRADO' AND [FechaCierre] IS NOT NULL AND [CerradoPor] IS NOT NULL))
GO
ALTER TABLE [Contabilidad].[PeriodoContable] CHECK CONSTRAINT [CK_PeriodoContable_Estado]
GO
ALTER TABLE [Contabilidad].[PeriodoContable]  WITH CHECK ADD  CONSTRAINT [CK_PeriodoContable_Mes] CHECK  (([Mes]>=(1) AND [Mes]<=(12)))
GO
ALTER TABLE [Contabilidad].[PeriodoContable] CHECK CONSTRAINT [CK_PeriodoContable_Mes]
GO
ALTER TABLE [Contabilidad].[TiposAsiento]  WITH CHECK ADD  CONSTRAINT [CK_TiposAsiento_CodigoFormato] CHECK  ((([Codigo]) collate Latin1_General_BIN2 like '[A-Z]%[_][A-Z0-9]%' AND NOT ([Codigo]) collate Latin1_General_BIN2 like '%[^A-Z0-9_]%'))
GO
ALTER TABLE [Contabilidad].[TiposAsiento] CHECK CONSTRAINT [CK_TiposAsiento_CodigoFormato]
GO
ALTER TABLE [Contabilidad].[TiposAsiento]  WITH CHECK ADD  CONSTRAINT [CK_TiposAsiento_Estado] CHECK  (([Estado]='I' OR [Estado]='A'))
GO
ALTER TABLE [Contabilidad].[TiposAsiento] CHECK CONSTRAINT [CK_TiposAsiento_Estado]
GO
ALTER TABLE [Organizacion].[Agencia]  WITH CHECK ADD  CONSTRAINT [CK_Agencia_Estado] CHECK  (([Estado]='C' OR [Estado]='I' OR [Estado]='A'))
GO
ALTER TABLE [Organizacion].[Agencia] CHECK CONSTRAINT [CK_Agencia_Estado]
GO
ALTER TABLE [Organizacion].[Agencia]  WITH CHECK ADD  CONSTRAINT [CK_Agencia_Tipo] CHECK  (([TipoAgencia]='Sucursal' OR [TipoAgencia]='Matriz'))
GO
ALTER TABLE [Organizacion].[Agencia] CHECK CONSTRAINT [CK_Agencia_Tipo]
GO
CREATE FUNCTION [Contabilidad].[fn_IdFechaContable] (@FechaHora datetime2)
RETURNS int
AS
BEGIN
    DECLARE @d date = CAST(@FechaHora AS date), @corte time(0), @id int;

    SELECT @corte = HoraCorte
    FROM Contabilidad.FechaContable
    WHERE Fecha = @d;

    IF @corte IS NOT NULL AND CAST(@FechaHora AS time(7)) >= @corte
        SET @d = DATEADD(day, 1, @d);

    SELECT TOP (1) @id = IdFechaContable
    FROM Contabilidad.FechaContable
    WHERE Fecha >= @d AND EsDiaContable = 1
    ORDER BY Fecha;

    RETURN @id;
END;
GO
CREATE   PROCEDURE [Contabilidad].[usp_ContabilizarAsiento]
    @IdAsientoContable int
AS
/* CO-01: calcula los totales desde las líneas y deja el asiento CONTABILIZADO.
   El asiento debe estar en BORRADOR o PENDIENTE_APROBACION; el trigger del asiento valida el resto. */
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;
    DECLARE @Estado varchar(20), @Deb decimal(18,2), @Cre decimal(18,2);
    SELECT @Estado = Estado FROM Contabilidad.AsientoContable WITH (UPDLOCK) WHERE IdAsientoContable = @IdAsientoContable;
    IF @Estado IS NULL THROW 51401, N'El asiento no existe.', 1;
    IF @Estado NOT IN ('BORRADOR','PENDIENTE_APROBACION') THROW 51402, N'Solo se contabiliza un asiento en BORRADOR o PENDIENTE_APROBACION.', 1;
    SELECT @Deb = ISNULL(SUM(CASE WHEN TipoMovimiento = 'DEBITO' THEN Monto END), 0),
           @Cre = ISNULL(SUM(CASE WHEN TipoMovimiento = 'CREDITO' THEN Monto END), 0)
    FROM Contabilidad.MovimientosContables WHERE IdAsientoContable = @IdAsientoContable;
    IF @Deb <> @Cre THROW 51403, N'Las líneas del asiento no cuadran (débitos distintos de créditos).', 1;
    UPDATE Contabilidad.AsientoContable SET TotalDebito = @Deb, TotalCredito = @Cre, Estado = 'CONTABILIZADO'
    WHERE IdAsientoContable = @IdAsientoContable;
END;
GO
CREATE   PROCEDURE [Contabilidad].[usp_GenerarNumeroAsiento]
    @FechaAsiento   date,
    @IdAgencia      char(3),
    @NumeroAsiento  varchar(20) OUTPUT
AS
/* Siguiente NumeroAsiento con formato YYYYMMDD-AAA-000001. Llamar dentro de la transacción que inserta el asiento. */
BEGIN
    SET NOCOUNT ON;
    IF @FechaAsiento IS NULL OR @IdAgencia IS NULL THROW 51301, N'FechaAsiento e IdAgencia son obligatorios.', 1;
    IF NOT EXISTS (SELECT 1 FROM Organizacion.Agencia WHERE IdAgencia = @IdAgencia) THROW 51302, N'La agencia no existe.', 1;
    IF @@TRANCOUNT = 0 THROW 51303, N'Llame a este procedimiento dentro de la transacción que inserta el asiento.', 1;
    DECLARE @Prefijo varchar(13) = CONCAT(CONVERT(char(8), @FechaAsiento, 112), '-', @IdAgencia, '-'), @Siguiente int;
    SELECT @Siguiente = ISNULL(MAX(TRY_CAST(RIGHT(NumeroAsiento, 6) AS int)), 0) + 1
    FROM Contabilidad.AsientoContable WITH (UPDLOCK, HOLDLOCK)
    WHERE NumeroAsiento LIKE @Prefijo + '[0-9][0-9][0-9][0-9][0-9][0-9]';
    IF @Siguiente > 999999 THROW 51304, N'Se agotó el secuencial diario de asientos para la agencia.', 1;
    SET @NumeroAsiento = CONCAT(@Prefijo, RIGHT(CONCAT('000000', @Siguiente), 6));
END;
GO
