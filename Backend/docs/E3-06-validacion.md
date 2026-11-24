# E3-06 · Activar, suspender y retirar productos

Las solicitudes de estado usan la cola E0-08. La ejecución vuelve a revisar la lista de activación y las restricciones de retiro. El historial consulta las solicitudes ejecutadas y la fecha registrada en su transición.

## Plantillas de E4-01

El motor y la selección de versiones vigentes están en `develop` desde `c04ee38`. Para depósitos en ventanilla de cuentas de ahorro, E4-01 documenta `CAJA_DEPOSITO`, con `CAPITAL` como rol del producto. La plantilla está vigente en la copia SQL local. El mismo documento deja pendiente la matriz de retiro y la definición por operación y subproducto para ATM. Los códigos de dotación y devolución de efectivo corresponden a custodia y no prueban requisitos de activación de un producto.

La lista mantiene `PLANTILLAS` pendiente donde falta una correspondencia completa y bloquea la activación. Para finalizar el ensayo con dos personas se necesita la matriz confirmada y una cuenta QA con `prd-estado` además de un aprobador independiente con `productos:aprobar`. La consulta de WorkOS de desarrollo encontró roles con permiso de aprobación y ningún rol con permiso de solicitud.

## Criterio 5

E6-01 debe integrar una revalidación en el punto de aprobación de una apertura pendiente. Debe leer el estado vigente del producto padre y del subproducto antes de crear o habilitar la cuenta, y rechazar la solicitud desactualizada si alguno dejó de estar activo. La apertura directa CTA-01 ya verifica ambos estados pero no tiene una solicitud pendiente que aprobar. Este cambio deja E6-01 para su propia integración y E3-06 abierta.

## Azure y reversión

`202611232230_productos_estado_aprobacion` registra `PRD-ESTADO` en `Seguridad.TransaccionesInterfaz` y `PRD_ESTADO_CAMBIADO` en `Auditoria.TipoEvento`. La cola requiere la primera fila para aceptar solicitudes. La segunda cataloga el evento que emite la operación. La migración no concede permisos de WorkOS.

Antes de aplicarla en Azure, consultar ambas claves en SeguridadDB y verificar un respaldo recuperable. Si las filas ya existen y coinciden con la configuración, ejecutar el alta mantiene una sola fila por clave. Una configuración incompatible aborta sin sobrescribirla. El script de reversión conserva la configuración cuando existen solicitudes de estado. El ensayo se limitó a SQL local.
