# E4-03 Administrar plantillas

Esta rama depende del código y de las migraciones E4-01.

- `GET /contabilidad/tipos-asiento/{id}/plantillas` lista versiones.
- `GET /contabilidad/plantillas/{id}` incluye el detalle.
- `POST /contabilidad/tipos-asiento/{id}/plantillas` guarda una nueva versión
  pendiente y devuelve 202. Requiere una plantilla base única para el tipo.
- `POST /contabilidad/plantillas/simulaciones` recibe líneas, montos de
  ejemplo y un mapa de cuentas para los roles en prueba. Devuelve las líneas
  y el total de débitos usando el mismo resolvedor del motor.

Las rutas usan el permiso WorkOS `con-plantilla-editar`. El manejador
interno `confirmar_aprobacion` exige una transacción, una segunda identidad
y una vigencia futura. Al activarse, delimita el fin de vigencia de la
versión anterior. Los disparadores de E4-01 protegen el detalle registrado.

La creacion devuelve 202 con `idPlantillaAsiento` e `idSolicitud`.
La cola E0-08 resuelve `CON-PLANTILLA` con sus endpoints de aprobar y rechazar.
El solicitante requiere CONTADOR y `con-plantilla-editar`. El aprobador requiere
el permiso efectivo `con-plantilla-aprobar` en WorkOS y debe ser otra persona.
Al ejecutar se registra `CON_PLANTILLA_PROGRAMADA`. Una solicitud rechazada
conserva la version inactiva y el resultado historico en E0-08. Cree una nueva
version para presentar una propuesta distinta.

La version y la solicitud se guardan en bases diferentes. Si falla la cola
despues de guardar la version, el creador puede listar las versiones y enviar
esa version con `POST /contabilidad/plantillas/{id_plantilla}/solicitudes`.
El envio no vuelve a crear la version y se admite una sola solicitud por
version, incluso cuando ya fue resuelta. El motor nunca usa versiones inactivas.

Instalar primero E4-01 y los catalogos de aprobaciones y auditoria. Luego
aplicar `202611191500_plantillas_aprobacion.up.sql` en SeguridadDB con
`migration_database` configurado. La asignacion efectiva de WorkOS se verifica
en el entorno antes de habilitar el flujo. Falta definir la cobertura exigida
por producto o subproducto para cada familia.

Prueba local: con PYTHONPATH apuntando a Backend, ejecute
tests/integration/e403_sql_lab.py con la base local ya preparada por el
ensayo de E4-01. Los IDs de usuario del ensayo son datos del laboratorio.

Cuando un tipo tenga varias familias, indique codigoPlantilla al crear su
versión. El GET del tipo devuelve este código para seleccionar la familia.
