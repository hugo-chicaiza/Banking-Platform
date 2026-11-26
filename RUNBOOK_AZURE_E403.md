# Registro y aprobación E4-03 en Azure

Este procedimiento se preparó sin ejecutar escrituras en Azure. Aplicar primero en dev autorizado. La ampliación vive en la rama `feat/contabilidad-e403-ampliacion`, desde `origin/develop` en `905bec0`. Un merge a `develop` dispara el despliegue de `backend-dev`. Esperar autorización de despliegue antes de integrar la rama al remoto.

## Fecha límite

La fecha propuesta es el **27 de noviembre de 2026**. La lectura de CooperativaDB dev confirmó que el día contable vigente era el 26, el 27 es hábil y el corte del 26 está configurado a las **19:00 de Ecuador**. Antes de presentar cada lote y antes de cada aprobación, consultar `GET /api/v1/contabilidad/fechas-contables/actual`. La fecha propuesta solo es válida mientras el día contable devuelto sea anterior al 27. Reservar tiempo para simulación, registro y aprobación independiente. La fecha debe seguir siendo futura en ambas llamadas.

Si el sistema ya resuelve el 27, o la segunda persona no puede completar la aprobación a tiempo, regenerar con el siguiente día contable futuro autorizado. El calendario consultado tiene el lunes 30 como siguiente día hábil después del 27. Si se perdió la ventana con solicitudes pendientes, resolverlas por el flujo de aprobación y revisar sus borradores antes de presentar nuevas versiones. El registrador de alta inicial se detiene cuando la familia ya existe con otra fecha. En ese caso usar el flujo oficial de nueva versión tras reconciliar, con `soloPrimeraVersion=false`; conservar el historial.

## Secuencia de ejecución

| Orden | Acción | Evidencia para continuar |
| --- | --- | --- |
| 1 | Confirmar destino, respaldo recuperable, fecha contable y período del 27. Confirmar identidad de solicitante y aprobador distintos, permiso de aprobación y MFA para la acción sensible. | En SeguridadDB dev se comprobó `CON-PLANTILLA` activa y sensible, con permiso `con-plantilla-aprobar`, y el evento `CON_PLANTILLA_PROGRAMADA`. En otro destino, cotejar con `202611191500_plantillas_aprobacion.up.sql`. Si falta alguno, aplicar la migración existente por el proceso autorizado antes de registrar. |
| 2 | Verificar AC-01, E4-01, E3-05 y E4-03 en CooperativaDB. | Selector versionado, roles E3-05, tipos y conceptos activos, cuentas hoja, agencias 001/002 activas para ARQUEO. Se comprobó en dev el índice `IX_AsientoContable_PlantillaAplicada` y el trigger `trg_Comisiones_RepTdbCuentaIngreso`. Para otro destino comprobar las migraciones existentes `202611251500_asientos_plantilla_uso` y `202611251501_rep_tdb_cuenta_ingreso`. |
| 3 | Ejecutar `preparar_paquete_contable.sql` en modo consulta para BASE. Simular, solicitar y aprobar primero estas cuatro familias. | Retiro de Caja, faltante de Caja, sobrante de Caja y pago desde cuenta de principal e interés devengado. Existen sus catálogos en dev. |
| 4 | Previsualizar ACTUAL y ARQUEO por separado. Crear los tipos y conceptos faltantes con el mismo SQL en modo de catálogo autorizado por DBA. Volver a consultar y guardar los JSON producidos. | Nueve familias ACTUAL sin ampliación y cuatro ARQUEO con agencias activas y ventana acordada con Bóveda. ARQUEO se limita a diferencias aprobadas, con efectos operativos desde la vigencia. |
| 5 | Una vez autorizado, integrar y desplegar el backend de la rama y distribuir el registrador actualizado. Verificar `/openapi.json` y el contrato de las bases. Preparar los metadatos y el JSON de AMPLIACION. | Siete familias de certificados, redes y depósitos no cubiertos. Conservan componentes que el frontend actual ya acepta. |
| 6 | Crear catálogo y generar el JSON aislado de PRIMA. Para revisión visual, confirmar que el frontend contable admite `PRIMA_FIJA` y `PRIMA_VARIABLE`. Si se usa la API, revisar el JSON de detalle y la simulación con el segundo actor autorizado antes de que este apruebe por la API. | Una familia de prima. La API y el registrador actualizados ya admiten las bases. La ampliación del frontend se limita al enum de componentes de `plantillas.api.ts` y su prueba de detalle/simulación. |
| 7 | Por cada paquete en ejecución, simular con roles/cuentas del alcance, colocar JSON en el directorio autorizado y revisar el registrador en modo local. Luego registrar por la API autorizada. | Guardar ID de plantilla y solicitud E0-08. Mantener separados los cinco manifiestos. Las siete familias existentes no se envían como altas iniciales. |
| 8 | Otra persona revisa líneas, concepto, alcance y fecha. Aprobar en la cola o en `POST /api/v1/aprobaciones/{idSolicitud}/aprobar`, con MFA sensible si lo exige la política. | Aprobación ejecutada mientras la fecha propuesta siga siendo futura. Guardar evidencia y repetir el control por agencia donde aplique. |
| 9 | Pegar cada JSON en `verificar_manifiesto_contable.sql` y ejecutarlo en solo lectura. Consultar también `GET /api/v1/contabilidad/reglas-contables?fecha=2026-11-27&agencia=001` y repetir para 002 cuando aplique. | Cada fila debe indicar `APROBADA_Y_SELECCIONADA` y coincidir con el ID seleccionado por el motor en su fecha de inicio. Si se regeneró, sustituir la fecha en el GET. Luego el productor valida su primer hecho en el ambiente autorizado. |

Por paquete, en la misma sesión SQL, ejecutar primero:

```sql
EXEC sys.sp_set_session_context N'paquete_contable_vigencia', N'2026-11-27';
EXEC sys.sp_set_session_context N'paquete_contable_paquete', N'BASE'; -- cambiar según etapa
EXEC sys.sp_set_session_context N'paquete_contable_catalogo', 0;
-- Ejecutar preparar_paquete_contable.sql y revisar el diagnóstico.
-- Solo para alta de catálogos autorizada:
-- DECLARE @base sysname = DB_NAME();
-- EXEC sys.sp_set_session_context N'paquete_contable_base', @base;
-- EXEC sys.sp_set_session_context N'paquete_contable_catalogo', 1;
-- Ejecutar el mismo SQL y guardar exclusivamente su ManifiestoJSON.
```

Al finalizar, limpiar las cuatro claves de sesión con `sp_set_session_context` y valor `NULL`. En el puesto del operador, guardar el JSON UTF-8 bajo `~/.banking-platform/e403/manifiestos/`. Revisar con `python Backend/scripts/registrar_plantillas_e403.py e403-base.json`. Luego añadir `--registrar --url <origen-autorizado>/api/v1` y asegurar que dicho origen esté autorizado en `E403_API_ORIGENES_AUTORIZADOS`. El registrador envía solicitudes, la segunda persona aprueba.

La ampliación **no requiere migración de esquema**: las familias usan orígenes ya aceptados por AC-01, y `ComponenteImporte` admite texto de hasta 30 caracteres. El SQL de metadatos registra datos de catálogo. La compatibilidad frontend se comprobó en `develop` web en `d72f629`. El enum cerrado también valida el detalle de una versión, por lo que PRIMA debe coordinarse con la interfaz antes de usarla allí. [Contrato actual del editor web](https://github.com/Djtv1304/banking-platform-front/blob/d72f629bb9a18af3d5671a9318a7675cdf721ba2/src/features/contabilidad/api/plantillas.api.ts)

[Familias y decisiones pendientes](PAQUETE_REGISTRO_CONTABLE.md)
