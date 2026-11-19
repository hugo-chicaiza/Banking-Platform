-- Esquema representativo real, sin filas de clientes; solo laboratorio SQL local propio.

IF SCHEMA_ID(N'Auditoria') IS NULL EXEC(N'CREATE SCHEMA [Auditoria]');

IF SCHEMA_ID(N'Organizacion') IS NULL EXEC(N'CREATE SCHEMA [Organizacion]');

IF SCHEMA_ID(N'Seguridad') IS NULL EXEC(N'CREATE SCHEMA [Seguridad]');

CREATE TABLE Auditoria.Auditoria (
 [AuditoriaID] int IDENTITY(1,1) NOT NULL,
 [UsuarioID] int NULL,
 [NombreAccion] varchar(100) NOT NULL,
 [TablaAfectada] varchar(100) NULL,
 [IDRegistro] varchar(100) NULL,
 [FechaHora] datetime NOT NULL DEFAULT (getdate()),
 [DireccionIP] varchar(45) NULL,
 [Descripcion] varchar(500) NULL,
 [Resultado] varchar(15) NOT NULL,
 [RolesWorkOS] varchar(200) NULL
);

CREATE TABLE Organizacion.UsuarioAgencia (
 [UsuarioID] int NOT NULL,
 [IdAgencia] char(3) NOT NULL,
 [Activo] bit NOT NULL DEFAULT ((1)),
 [FechaAsignacion] datetime2(7) NOT NULL DEFAULT (sysutcdatetime()),
 [AsignadoPor] int NULL,
 [Origen] varchar(16) NOT NULL
);

CREATE TABLE Organizacion.UsuarioAgenciaHistorial (
 [IdHistorial] bigint IDENTITY(1,1) NOT NULL,
 [UsuarioID] int NOT NULL,
 [IdAgencia] char(3) NULL,
 [Accion] varchar(20) NOT NULL,
 [PrincipalAnterior] char(3) NULL,
 [PrincipalNueva] char(3) NULL,
 [RealizadoPor] int NULL,
 [AgenciaActor] char(3) NULL,
 [FechaUTC] datetime2(7) NOT NULL DEFAULT (sysutcdatetime())
);

CREATE TABLE Organizacion.Usuarios (
 [UsuarioID] int IDENTITY(1,1) NOT NULL,
 [NombreUsuario] varchar(50) NOT NULL,
 [Nombres] varchar(100) NOT NULL,
 [Apellidos] varchar(100) NOT NULL,
 [Email] varchar(100) NOT NULL,
 [Estado] varchar(15) NOT NULL DEFAULT ('Activo'),
 [IntentosFallidos] int NOT NULL DEFAULT ((0)),
 [FechaCreacion] datetime NOT NULL DEFAULT (getdate()),
 [UltimoAcceso] datetime NULL,
 [Cedula] varchar(10) NOT NULL,
 [UltimaSesionID] int NULL,
 [AgenciaID] int NULL,
 [KeyUsuario] varchar(64) NULL,
 [RolesWorkOS] varchar(200) NULL
);

CREATE TABLE Seguridad.Bloqueos (
 [BloqueoID] int IDENTITY(1,1) NOT NULL,
 [UsuarioID] int NOT NULL,
 [MotivoBloqueo] varchar(30) NOT NULL,
 [FechaBloqueo] datetime NOT NULL DEFAULT (getdate()),
 [FechaDesbloqueo] datetime NULL,
 [BloqueadoPor] int NOT NULL,
 [DesbloqueadoPor] int NULL,
 [Observaciones] varchar(300) NULL
);

CREATE TABLE Seguridad.ContextoAgenciaSesion (
 [IdSesionHash] binary(32) NOT NULL,
 [UsuarioID] int NOT NULL,
 [IdAgencia] char(3) NOT NULL,
 [FechaCambioUTC] datetime2(7) NOT NULL DEFAULT (sysutcdatetime()),
 [ExpiraUTC] datetime2(7) NOT NULL
);

CREATE TABLE Seguridad.PestanaRol (
 [Pestana] varchar(80) NOT NULL,
 [Roles] varchar(200) NOT NULL,
 [ModificadoPor] int NOT NULL,
 [FechaModificacion] datetime2(7) NOT NULL DEFAULT (sysutcdatetime())
);

ALTER TABLE Auditoria.Auditoria ADD CONSTRAINT [PK__Auditori__095694E3394D5473] PRIMARY KEY ([AuditoriaID]);

ALTER TABLE Organizacion.UsuarioAgencia ADD CONSTRAINT [PK_UsuarioAgencia] PRIMARY KEY ([UsuarioID],[IdAgencia]);

CREATE INDEX [IX_UAH_Usuario] ON Organizacion.UsuarioAgenciaHistorial([UsuarioID],[IdHistorial]);

ALTER TABLE Organizacion.UsuarioAgenciaHistorial ADD CONSTRAINT [PK_UsuarioAgenciaHistorial] PRIMARY KEY ([IdHistorial]);

ALTER TABLE Organizacion.Usuarios ADD CONSTRAINT [PK__Usuarios__2B3DE798C0038926] PRIMARY KEY ([UsuarioID]);

CREATE UNIQUE INDEX [UQ__Usuarios__6B0F5AE0CCFA99E9] ON Organizacion.Usuarios([NombreUsuario]);

CREATE UNIQUE INDEX [UQ__Usuarios__A9D105349AFE5CD0] ON Organizacion.Usuarios([Email]);

CREATE UNIQUE INDEX [UQ__Usuarios__B4ADFE38A3CE0026] ON Organizacion.Usuarios([Cedula]);

CREATE UNIQUE INDEX [UX_Usuarios_KeyUsuario] ON Organizacion.Usuarios([KeyUsuario]) WHERE ([KeyUsuario] IS NOT NULL);

ALTER TABLE Seguridad.Bloqueos ADD CONSTRAINT [PK__Bloqueos__4F0C43DDF9E2A1E9] PRIMARY KEY ([BloqueoID]);

ALTER TABLE Seguridad.ContextoAgenciaSesion ADD CONSTRAINT [PK_ContextoAgenciaSesion] PRIMARY KEY ([IdSesionHash]);

ALTER TABLE Seguridad.PestanaRol ADD CONSTRAINT [PK_PestanaRol] PRIMARY KEY ([Pestana]);

ALTER TABLE Organizacion.UsuarioAgencia ADD CONSTRAINT [CK_UA_Origen] CHECK ([Origen]='Administrador' OR [Origen]='Migracion');

ALTER TABLE Organizacion.UsuarioAgencia ADD CONSTRAINT [CK_UA_Autor] CHECK ([Origen]='Migracion' OR [AsignadoPor] IS NOT NULL);

ALTER TABLE Organizacion.UsuarioAgencia ADD CONSTRAINT [CK_UA_Agencia] CHECK ([IdAgencia] like '[0-9][0-9][0-9]' AND [IdAgencia]<>'000');

ALTER TABLE Organizacion.UsuarioAgenciaHistorial ADD CONSTRAINT [CK_UAH_Accion] CHECK ([Accion]='PRINCIPAL' OR [Accion]='REVOCAR' OR [Accion]='ASIGNAR' OR [Accion]='MIGRACION');

ALTER TABLE Organizacion.UsuarioAgenciaHistorial ADD CONSTRAINT [CK_UAH_Autor] CHECK ([Accion]='MIGRACION' OR [RealizadoPor] IS NOT NULL);

ALTER TABLE Seguridad.PestanaRol ADD CONSTRAINT [CK_PestanaRol_Pestana] CHECK ([Pestana] like '/%' AND NOT ([Pestana]='/seguridad/pestanas' OR [Pestana]='/seguridad/roles' OR [Pestana]='/'));

ALTER TABLE Auditoria.Auditoria ADD CONSTRAINT [CHK_Auditoria_Resultado] CHECK ([Resultado]='Fallido' OR [Resultado]='Exitoso');

ALTER TABLE Organizacion.Usuarios ADD CONSTRAINT [CHK_Usuarios_Cedula_Formato] CHECK (NOT [Cedula] like '%[^0-9]%' AND len([Cedula])=(10));

ALTER TABLE Organizacion.Usuarios ADD CONSTRAINT [CHK_Usuarios_Estado] CHECK ([Estado]='Bloqueado' OR [Estado]='Inactivo' OR [Estado]='Activo');

-- Dependencia publicada en develop: editor de funciones.
IF OBJECT_ID(N'Seguridad.AccesoFuncionRol', N'U') IS NULL
    CREATE TABLE Seguridad.AccesoFuncionRol (
        Funcion varchar(80) NOT NULL,
        Rol varchar(32) NOT NULL,
        Permitido bit NOT NULL,
        ModificadoPor int NOT NULL,
        FechaModificacion datetime2 NOT NULL CONSTRAINT DF_AccesoFuncionRol_Fecha DEFAULT SYSUTCDATETIME(),
        CONSTRAINT PK_AccesoFuncionRol PRIMARY KEY (Funcion, Rol),
        CONSTRAINT FK_AccesoFuncionRol_Usuario FOREIGN KEY (ModificadoPor) REFERENCES Organizacion.Usuarios(UsuarioID),
        CONSTRAINT CK_AccesoFuncionRol_Funcion CHECK (LEN(Funcion)>0 AND Funcion NOT LIKE '%[^a-zA-Z0-9.]%' COLLATE Latin1_General_100_BIN2),
        CONSTRAINT CK_AccesoFuncionRol_Rol CHECK (Rol IN ('ADMIN','SUPERVISOR','ASESOR','CAJERO','CONTADOR','AUDITOR','APROBADOR_CREDITO'))
    );
