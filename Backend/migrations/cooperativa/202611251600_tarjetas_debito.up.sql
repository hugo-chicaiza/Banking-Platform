SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57710, 'Confirme la base destino de E6-10.', 1;

BEGIN TRANSACTION;

IF OBJECT_ID(N'Catalogo.MotivoEstadoTarjeta', N'U') IS NULL
BEGIN
    CREATE TABLE Catalogo.MotivoEstadoTarjeta (
        Codigo varchar(30) NOT NULL CONSTRAINT PK_MotivoEstadoTarjeta PRIMARY KEY,
        Nombre nvarchar(80) NOT NULL,
        PermiteDesbloqueo bit NOT NULL,
        Estado char(1) NOT NULL CONSTRAINT DF_MotivoEstadoTarjeta_Estado DEFAULT ('A'),
        CONSTRAINT CK_MotivoEstadoTarjeta_Estado CHECK (Estado IN ('A','I'))
    );
END;

INSERT Catalogo.MotivoEstadoTarjeta (Codigo, Nombre, PermiteDesbloqueo)
SELECT v.Codigo, v.Nombre, v.PermiteDesbloqueo
FROM (VALUES
    ('PERDIDA', N'Pérdida', 0),
    ('ROBO', N'Robo', 0),
    ('SOSPECHA_FRAUDE', N'Sospecha de fraude', 1),
    ('PEDIDO_CLIENTE', N'Pedido del cliente', 1),
    ('OTRA', N'Otra causa', 1),
    ('NO_RETIRADA', N'No retirada', 0),
    ('CIERRE_CUENTA', N'Cierre de la cuenta', 0),
    ('PRODUCTO_SUSPENDIDO', N'Producto suspendido', 0)
) v(Codigo, Nombre, PermiteDesbloqueo)
WHERE NOT EXISTS (
    SELECT 1 FROM Catalogo.MotivoEstadoTarjeta m WITH (UPDLOCK,HOLDLOCK)
    WHERE m.Codigo = v.Codigo
);

IF COL_LENGTH('Tarjeta.Tarjeta', 'IdTarjetaReemplazada') IS NULL
    ALTER TABLE Tarjeta.Tarjeta ADD IdTarjetaReemplazada int NULL
        CONSTRAINT FK_Tarjeta_Reemplazada REFERENCES Tarjeta.Tarjeta (IdTarjeta);
IF COL_LENGTH('Tarjeta.Tarjeta', 'MotivoEstado') IS NULL
    ALTER TABLE Tarjeta.Tarjeta ADD MotivoEstado varchar(30) NULL
        CONSTRAINT FK_Tarjeta_MotivoEstado REFERENCES Catalogo.MotivoEstadoTarjeta (Codigo);
IF COL_LENGTH('Tarjeta.Tarjeta', 'EntregaVerificadaEn') IS NULL
    ALTER TABLE Tarjeta.Tarjeta ADD EntregaVerificadaEn datetime2(0) NULL;
IF COL_LENGTH('Tarjeta.Tarjeta', 'SobreDescargadoEn') IS NULL
    ALTER TABLE Tarjeta.Tarjeta ADD SobreDescargadoEn datetime2(0) NULL;
IF COL_LENGTH('Tarjeta.Tarjeta', 'RequiereEntregaVerificada') IS NULL
    ALTER TABLE Tarjeta.Tarjeta ADD RequiereEntregaVerificada bit NOT NULL
        CONSTRAINT DF_Tarjeta_EntregaVerificada DEFAULT (0);
IF COL_LENGTH('Tarjeta.EnviosTarjeta', 'CodigoSeguimiento') IS NULL
    ALTER TABLE Tarjeta.EnviosTarjeta ADD CodigoSeguimiento varchar(64) NULL;
IF COL_LENGTH('Tarjeta.EnviosTarjeta', 'DespachadoEn') IS NULL
    ALTER TABLE Tarjeta.EnviosTarjeta ADD DespachadoEn datetime2(0) NULL;

COMMIT;
