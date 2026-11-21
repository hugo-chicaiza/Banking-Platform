/* Ejecutar en CooperativaDB. Solo lectura. */
SELECT DB_NAME() AS Base, @@TRANCOUNT AS TransaccionesAbiertas,
       OBJECT_ID(N'Organizacion.Usuarios',N'U') AS UsuariosLocal,
       OBJECT_ID(N'E201.usp_EjecutarCorte',N'P') AS Motor004,
       OBJECT_ID(N'E201.usp_ValidarAprobacionCorte',N'P') AS Validador,
       OBJECT_ID(N'E201.usp_ValidarAprobacionSSMS',N'P') AS ValidadorSSMS,
       DATABASE_PRINCIPAL_ID(N'E201_ServicioWorkOS') AS RolServicio,
       COL_LENGTH(N'E201.PermisoWorkOS',N'Sujeto') AS ColumnaSujeto;

SELECT name,type_desc FROM sys.objects
WHERE schema_id=SCHEMA_ID(N'E201') AND name LIKE N'%WorkOS%'
ORDER BY name;

SELECT name, OBJECT_SCHEMA_NAME(referenced_object_id) EsquemaDestino,
       OBJECT_NAME(referenced_object_id) TablaDestino
FROM sys.foreign_keys WHERE parent_object_id=OBJECT_ID(N'E201.PermisoWorkOS');
