/* E0-05 · Formato nuevo de la bitácora de auditoría (SeguridadDB). Aditiva.
   - Auditoria.TipoEvento: catálogo de eventos (CodigoEvento) con módulo y severidad. La prueba
     tests/unit/test_auditoria_formato.py exige que cada código del código esté aquí.
   - Columnas nuevas en Auditoria.Auditoria: identificador del evento, código, hora UTC, agencia,
     sesión, canal, correlación, objetivo y cambios. Las filas existentes quedan con
     FormatoAnterior = 1 SIN UPDATE (el disparador de E0-08 protege los eventos vinculados):
     se agrega la columna con DEFAULT 1 y luego el valor por defecto pasa a 0.
     Su hora UTC se calcula al consultar: DATEADD(hour, 5, FechaHora) (Ecuador, UTC-5 sin verano).
   - Disparador: la bitácora solo admite inserciones (ASVS 16.4.2).
   CodigoEvento no tiene FK al catálogo: un código ausente haría perder el evento; la prueba
   del pipeline cumple ese control. */
SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128),SESSION_CONTEXT(N'migration_database')),N'')<>DB_NAME()
 THROW 57205,'Falta confirmar la base destino de la migracion.',1;
IF DB_NAME()<>N'SeguridadDB' THROW 57205,'La migracion requiere SeguridadDB.',1;
BEGIN TRANSACTION;
BEGIN TRY
 IF OBJECT_ID('Auditoria.TipoEvento','U') IS NULL
  CREATE TABLE Auditoria.TipoEvento(
   CodigoEvento varchar(100) NOT NULL CONSTRAINT PK_TipoEvento PRIMARY KEY,
   Modulo varchar(30) NOT NULL,
   Severidad varchar(12) NOT NULL CONSTRAINT CK_TipoEvento_Severidad CHECK (Severidad IN ('Informativo','Sensible','Seguridad')),
   EnTransaccion bit NOT NULL,
   Estado char(1) NOT NULL CONSTRAINT DF_TipoEvento_Estado DEFAULT ('A'));
 MERGE Auditoria.TipoEvento AS d USING (VALUES
  ('ABRIR_JORNADA', 'caja', 'Sensible', 1),
  ('ACCESO_DENEGADO', 'seguridad', 'Seguridad', 0),
  ('ACTUALIZAR', 'general', 'Informativo', 0),
  ('APROBAR_ARQUEO_BOVEDA', 'boveda', 'Sensible', 1),
  ('APROBAR_SOLICITUD_BOVEDA', 'boveda', 'Sensible', 1),
  ('APR_AUTOAPROBACION_INTENTO', 'aprobaciones', 'Sensible', 0),
  ('APR_SOLICITUD_CANCELADA', 'aprobaciones', 'Sensible', 0),
  ('APR_SOLICITUD_CREADA', 'aprobaciones', 'Sensible', 0),
  ('APR_SOLICITUD_RESUELTA', 'aprobaciones', 'Sensible', 0),
  ('ARQUEO_BOVEDA', 'boveda', 'Sensible', 1),
  ('ASIGNAR_AGENCIAS', 'seguridad', 'Seguridad', 0),
  ('ASIGNAR_PERMISO_ROL', 'seguridad', 'Seguridad', 0),
  ('AUTORIZAR_CUADRE', 'caja', 'Sensible', 1),
  ('BORRAR_PERMISO', 'seguridad', 'Seguridad', 0),
  ('CAMBIAR_CONTEXTO', 'seguridad', 'Seguridad', 0),
  ('CAMBIAR_ROL', 'seguridad', 'Seguridad', 0),
  ('CANCELAR_JORNADA', 'caja', 'Sensible', 1),
  ('CERRAR_JORNADA', 'caja', 'Sensible', 1),
  ('CONFIGURAR_ACCESOS', 'seguridad', 'Seguridad', 0),
  ('CONFIGURAR_FUNCION', 'seguridad', 'Seguridad', 0),
  ('CONFIGURAR_PESTANAS', 'seguridad', 'Seguridad', 0),
  ('CON_CATALOGO_IMPORTADO', 'contabilidad', 'Sensible', 0),
  ('CON_CUENTA_CREADA', 'contabilidad', 'Sensible', 0),
  ('CON_CUENTA_EDITADA', 'contabilidad', 'Sensible', 0),
  ('CON_CUENTA_ESTADO', 'contabilidad', 'Sensible', 0),
  ('CREAR', 'general', 'Informativo', 0),
  ('CREAR_ENTIDAD', 'organizacion', 'Informativo', 0),
  ('CREAR_PERMISO', 'seguridad', 'Seguridad', 0),
  ('EDITAR_ENTIDAD', 'organizacion', 'Informativo', 0),
  ('EDITAR_PERMISO', 'seguridad', 'Seguridad', 0),
  ('ELIMINAR', 'general', 'Informativo', 0),
  ('GENERAR_CUADRE', 'caja', 'Sensible', 1),
  ('LOGIN', 'seguridad', 'Seguridad', 0),
  ('LOGOUT', 'seguridad', 'Seguridad', 0),
  ('QUITAR_PERMISO_ROL', 'seguridad', 'Seguridad', 0),
  ('REEMPLAZAR_PERMISOS_ROL', 'seguridad', 'Seguridad', 0),
  ('REGISTRAR_CONTEO', 'caja', 'Sensible', 1),
  ('REGISTRAR_DEVOLUCION', 'caja', 'Sensible', 1),
  ('REGISTRAR_DOTACION', 'caja', 'Sensible', 1),
  ('REGISTRAR_SERIES', 'caja', 'Sensible', 1),
  ('RESOLVER_SOLICITUD_BOVEDA', 'boveda', 'Sensible', 1),
  ('REVERSAR_TRANSACCION', 'transacciones', 'Sensible', 1),
  ('SOLICITAR_MOVIMIENTO_BOVEDA', 'boveda', 'Sensible', 1),
  ('UPDATE', 'general', 'Informativo', 0),
  ('VINCULAR', 'seguridad', 'Seguridad', 0),
  ('PRD_SUBPRODUCTO_EDITADO', 'productos', 'Informativo', 0),
  ('INSERT', 'general', 'Informativo', 0),
  ('PRD_PRODUCTO_EDITADO', 'productos', 'Informativo', 0),
  ('APR_OPERACION_EJECUTADA', 'aprobaciones', 'Sensible', 0),
  ('PRD_PRODUCTO_CREADO', 'productos', 'Informativo', 0),
  ('PAR_VALOR_REGISTRADO', 'parametros', 'Informativo', 0),
  ('DESBLOQUEO_USUARIO', 'seguridad', 'Seguridad', 0),
  ('PAR_VALOR_CANCELADO', 'parametros', 'Informativo', 0),
  ('SELECT', 'general', 'Informativo', 0),
  ('PROCESO_VENCIMIENTO', 'creditos', 'Sensible', 0),
  ('APR_FIXTURE_QA_CREADA', 'aprobaciones', 'Sensible', 0)
 ) AS o(CodigoEvento, Modulo, Severidad, EnTransaccion) ON d.CodigoEvento=o.CodigoEvento
 WHEN MATCHED THEN UPDATE SET Modulo=o.Modulo, Severidad=o.Severidad, EnTransaccion=o.EnTransaccion
 WHEN NOT MATCHED THEN INSERT(CodigoEvento, Modulo, Severidad, EnTransaccion) VALUES(o.CodigoEvento, o.Modulo, o.Severidad, o.EnTransaccion);

 IF COL_LENGTH('Auditoria.Auditoria','FormatoAnterior') IS NULL
 BEGIN
  ALTER TABLE Auditoria.Auditoria ADD
   IdEvento uniqueidentifier NULL,
   CodigoEvento varchar(100) NULL,
   FechaHoraUTC datetime2 NULL,
   IdAgencia char(3) NULL,
   IdSesion varchar(64) NULL,
   Canal varchar(10) NULL,
   IdCorrelacion varchar(64) NULL,
   TipoObjetivo varchar(100) NULL,
   IdObjetivo varchar(100) NULL,
   Cambios nvarchar(max) NULL,
   FormatoAnterior bit NOT NULL CONSTRAINT DF_Auditoria_FormatoAnterior DEFAULT (1) WITH VALUES;
  ALTER TABLE Auditoria.Auditoria DROP CONSTRAINT DF_Auditoria_FormatoAnterior;
  ALTER TABLE Auditoria.Auditoria ADD CONSTRAINT DF_Auditoria_FormatoNuevo DEFAULT (0) FOR FormatoAnterior;
 END;
 IF INDEXPROPERTY(OBJECT_ID('Auditoria.Auditoria'),'UX_Auditoria_IdEvento','IndexID') IS NULL
  EXEC('CREATE UNIQUE INDEX UX_Auditoria_IdEvento ON Auditoria.Auditoria(IdEvento) WHERE IdEvento IS NOT NULL');
 IF INDEXPROPERTY(OBJECT_ID('Auditoria.Auditoria'),'IX_Auditoria_FechaUTC','IndexID') IS NULL
  EXEC('CREATE INDEX IX_Auditoria_FechaUTC ON Auditoria.Auditoria(FechaHoraUTC)');
 IF INDEXPROPERTY(OBJECT_ID('Auditoria.Auditoria'),'IX_Auditoria_Correlacion','IndexID') IS NULL
  EXEC('CREATE INDEX IX_Auditoria_Correlacion ON Auditoria.Auditoria(IdCorrelacion) WHERE IdCorrelacion IS NOT NULL');
 IF INDEXPROPERTY(OBJECT_ID('Auditoria.Auditoria'),'IX_Auditoria_Objetivo','IndexID') IS NULL
  EXEC('CREATE INDEX IX_Auditoria_Objetivo ON Auditoria.Auditoria(TipoObjetivo, IdObjetivo)');
 EXEC('CREATE OR ALTER TRIGGER Auditoria.trg_Auditoria_SoloInsercion ON Auditoria.Auditoria AFTER UPDATE, DELETE AS
  BEGIN SET NOCOUNT ON; THROW 57201, N''La bitácora de auditoría no se modifica ni se elimina.'', 1; END');
 COMMIT TRANSACTION;
END TRY
BEGIN CATCH
 IF @@TRANCOUNT>0 ROLLBACK TRANSACTION;
 THROW;
END CATCH;
