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

La cola E0-08 debe autorizar al aprobador y conectar este manejador. El 202
persiste el estado pendiente. Faltan el envío a la cola, la validación de
cobertura de roles por subproducto, la asignación del permiso en el tenant, el evento de
programación y la interfaz de edición y simulación.

Prueba local: con PYTHONPATH apuntando a Backend, ejecute
tests/integration/e403_sql_lab.py con la base local ya preparada por el
ensayo de E4-01. Los IDs de usuario del ensayo son datos del laboratorio.

Cuando un tipo tenga varias familias, indique codigoPlantilla al crear su
versión. El GET del tipo devuelve este código para seleccionar la familia.
