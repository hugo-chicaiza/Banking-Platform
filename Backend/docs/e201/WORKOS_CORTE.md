# E2-01 · aprobación institucional por WorkOS

El criterio 5 separa a las personas que preparan y aprueban. En la API
ambas sesiones WorkOS pueden utilizar el mismo principal privado de servicio
en SQL Server. El canal SSMS de 004 sigue verificando dos identidades SQL
distintas cuando se usa ese canal.

## Instalación manual con 004 instalado

1. Revisar y ejecutar scripts/sql/e201/006_aprobacion_workos.sql. La
   migración conserva el verificador SSMS anterior y lo despacha para
   sus recibos positivos. Los recibos institucionales tienen IDs negativos.
2. El DBA debe vincular un principal SQL **privado de la API**, de mínimo
   privilegio, al rol E201_ServicioWorkOS. Darle acceso únicamente al
   procedimiento delegado por ese rol. La credencial no se comparte con
   operadores ni se concede el rol a devcat, al login de la aplicación
   general o a identidades humanas. Mantener al principal fuera de
   db_owner, db_datawriter y de roles de corte SSMS. Si devcat tiene
   privilegios de administración, sigue siendo parte de la frontera de
   confianza administrativa de toda la base.
3. Configurar WORKOS_ORGANIZATION_ID y las variables privadas
   E201_SERVICIO_SQL_USER y E201_SERVICIO_SQL_PASSWORD. Publicar en WorkOS
   con-reclasificacion-preparar y con-reclasificacion-aprobar y asignarlos
   a los usuarios aprobados. El DBA registra en E201.PermisoWorkOS sus
   permisos vigentes por UsuarioID existente en Organizacion.Usuarios.
   Revocar allí el permiso para impedir el uso de un recibo pendiente
   al ejecutar. La base revalida este permiso y el vínculo activo.
4. Desplegar la API. Bajo el prefijo /contabilidad/cortes-e201:
   - POST guarda el manifiesto. El cuerpo contiene IdCorte, FechaCorte,
     NumeroAsiento, IdFechaContable, IdAgencia, Controles y ConciliacionAhorro.
     La API genera IdPlan y SQL resuelve PreparadoPor desde la sesión
     institucional. Devuelve Contenido y HashPlan.
   - GET /{id_plan} permite a un aprobador ver el manifiesto congelado.
   - POST /{id_plan}/aprobaciones recibe hashPlan y comentario. El sujeto
     proviene de la sesión autenticada. La base verifica el hash, la
     separación de personas y la versión del objetivo, y emite el recibo.
5. Un ejecutor habilitado de SSMS llama E201.usp_EjecutarCorte con el
   IdSolicitud exacto, incluido su signo. El procedimiento existente
   revalida recibo, identidades activas y permisos de BD y ejecuta el
   mismo corte atómico. Conservar el ticket, hash y el asiento en la
   evidencia de despliegue.

No aplicar 004 de nuevo tras 006. Su última sección reinstala el validador
exclusivo de SSMS. Desactivar el canal API retirando el rol del principal
privado. Para detener un recibo institucional aún pendiente, retirar el
permiso efectivo en E201.PermisoWorkOS antes de ejecutar el corte. Los
asientos confirmados siguen el procedimiento de recuperación de E2-01.
