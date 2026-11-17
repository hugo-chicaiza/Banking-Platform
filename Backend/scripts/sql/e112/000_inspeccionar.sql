/* Solo lectura. Ejecutar en la base CooperativaDB de destino antes de 001/002.
   No presupone que el esquema local sea idéntico al de Azure. */
SELECT DB_NAME() AS BaseActual, @@VERSION AS VersionSQL;
SELECT c.name, TYPE_NAME(c.user_type_id) AS Tipo, c.is_nullable,c.is_identity,d.definition AS Defecto
FROM sys.columns c LEFT JOIN sys.default_constraints d ON d.object_id=c.default_object_id
WHERE c.object_id=OBJECT_ID('Transacciones.ComisionTipoTransaccion');
SELECT f.name,pc.name AS Columna,OBJECT_SCHEMA_NAME(f.referenced_object_id) AS EsquemaDestino,
       OBJECT_NAME(f.referenced_object_id) AS TablaDestino,rc.name AS ColumnaDestino
FROM sys.foreign_keys f JOIN sys.foreign_key_columns k ON k.constraint_object_id=f.object_id
JOIN sys.columns pc ON pc.object_id=k.parent_object_id AND pc.column_id=k.parent_column_id
JOIN sys.columns rc ON rc.object_id=k.referenced_object_id AND rc.column_id=k.referenced_column_id
WHERE f.parent_object_id=OBJECT_ID('Transacciones.ComisionTipoTransaccion');
SELECT IdCanal,CodigoCanal,Estado FROM Canal.Canal WHERE IdCanal IN (1,2,3);
SELECT * FROM Transacciones.Comisiones WHERE IdComision IN (1,2,3);
SELECT * FROM Transacciones.ComisionTipoTransaccion
WHERE CodigoTipoTransaccion IN ('Retiro','Transferencia_Enviada','Reposicion_Tarjeta','Cobro_Comision');
SELECT * FROM Transacciones.TipoTransaccion
WHERE CodigoTipo IN ('Retiro','Transferencia_Enviada','Reposicion_Tarjeta','Cobro_Comision');
SELECT OBJECT_DEFINITION(OBJECT_ID('Transacciones.fn_CalcularComision')) AS CobradorVigente;
SELECT name,definition,is_disabled,is_not_trusted FROM sys.check_constraints
WHERE parent_object_id=OBJECT_ID('Transacciones.ExoneracionComision');
