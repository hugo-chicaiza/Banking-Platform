SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57730, 'Confirme la base destino de E6-11.', 1;

BEGIN TRANSACTION;
IF COL_LENGTH('Tarjeta.Tarjeta', 'IdTarjetaReemplazada') IS NULL
    THROW 57731, 'Aplique primero el esquema de tarjetas de débito de E6-10.', 1;

INSERT Parametros.Parametro (Clave,Modulo,Descripcion,TipoDato,Unidad,ValorMinimo,ValorMaximo,EsSensible)
SELECT opciones.Clave,'Tarjetas',opciones.Descripcion,'Entero','dias',1,365,0
FROM (VALUES ('TAR_DIAS_AVISO_RENOVACION',N'Días de aviso previo para renovar una tarjeta'),
             ('TAR_DIAS_NO_RETIRADA',N'Días para anular una tarjeta generada sin retiro ni despacho')) opciones(Clave,Descripcion)
WHERE NOT EXISTS (SELECT 1 FROM Parametros.Parametro p WITH (UPDLOCK,HOLDLOCK) WHERE p.Clave=opciones.Clave);

INSERT Parametros.ParametroValor (IdParametro,Valor,VigenciaDesde,CreadoPor)
SELECT p.IdParametro,N'30',CONVERT(date,'19000101',112),NULL
FROM Parametros.Parametro p
WHERE p.Clave IN ('TAR_DIAS_AVISO_RENOVACION','TAR_DIAS_NO_RETIRADA') AND NOT EXISTS (
    SELECT 1 FROM Parametros.ParametroValor v WITH (UPDLOCK,HOLDLOCK) WHERE v.IdParametro=p.IdParametro
);

INSERT Tarjeta.TransicionEstado (EstadoOrigen,EstadoDestino)
SELECT opciones.EstadoOrigen,'Vencida' FROM (VALUES ('Inactiva'),('Bloqueada')) opciones(EstadoOrigen)
WHERE NOT EXISTS (
    SELECT 1 FROM Tarjeta.TransicionEstado t WITH (UPDLOCK,HOLDLOCK)
    WHERE t.EstadoOrigen=opciones.EstadoOrigen AND t.EstadoDestino='Vencida'
);
COMMIT TRANSACTION;
