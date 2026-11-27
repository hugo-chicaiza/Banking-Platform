# E5-08 · Archivos de la ficha del cliente

El backend reutiliza el servicio de documentos de E5-08. SQL conserva los metadatos de cada versión. MongoDB conserva los bytes cifrados. El nombre original es de presentación y el identificador público no revela la clave de MongoDB.

## Contrato de la ficha existente

| Operación bajo `/api/v1/clientes/{idCliente}/archivos` | Permiso | Resultado |
|---|---|---|
| `GET` | `CLI-ARCHIVO-VER` | `clases`, `maxBytes` y archivos con versión, estado del análisis e identificador de la versión anterior |
| `GET /clases` | `CLI-ARCHIVO` | Catálogo y tamaño máximo para quien puede cargar archivos |
| `POST` | `CLI-ARCHIVO` | `201` con la versión cargada. Multipart con `archivo`, `claseDocumento` y `reemplazarIdArchivo` opcional |
| `GET /{idArchivo}/contenido` | `CLI-ARCHIVO-VER` | Descarga con MIME verificado, nombre saneado, `attachment`, `no-store` y `nosniff` |

El backend verifica la ficha y la pertenencia del archivo en cada solicitud. Al reemplazar, la nueva versión recibe otro ID y conserva la referencia a la versión anterior. La segunda petición concurrente que intente reemplazar la misma versión vigente recibe `409 ARCHIVO_NO_REEMPLAZABLE`. Una versión histórica limpia se puede consultar por su identificador original.

El límite máximo de un archivo es 5.242.880 bytes y se puede reducir con `CLI_ARCHIVO_MAX_BYTES`. El backend verifica los bytes reales con el servicio compartido y exige el resultado de ClamAV antes de guardar. Los códigos incluyen `413 ARCHIVO_MUY_GRANDE`, `415 TIPO_NO_PERMITIDO`, `422 ARCHIVO_RECHAZADO`, `409 DOCUMENTO_NO_DISPONIBLE`, `503 ANALISIS_NO_DISPONIBLE` y `503 ALMACENAMIENTO_NO_DISPONIBLE`. Una vista autorizada requiere que se guarde `CLI_ARCHIVO_VISTO` con usuario, cliente y archivo. La API registra los rechazos del análisis y el middleware de seguridad registra las solicitudes denegadas.

Para sesiones con permisos de WorkOS, el backend usa los slugs `cli-archivo` y `cli-archivo-ver`. Cuando está activa la autorización por funciones, el catálogo incluye `clientes.archivos.gestionar` y `clientes.archivos.consultar`. Las asignaciones remotas se hacen según el proceso del equipo.

## Recorrido local

Usar una ficha ficticia, ambas bases SQL locales migradas y una clave de documentos de prueba. Desde `Backend`, `docker compose -f compose.archivos.local.yml up -d` inicia MongoDB y ClamAV en loopback. Esperar a que ClamAV cargue sus firmas. Configurar `MONGO_URI=mongodb://127.0.0.1:27028`, `MONGO_DB=banking_archivos_local`, `DOCUMENTOS_CLAMAV_HOST=127.0.0.1`, `DOCUMENTOS_CLAMAV_PORT=13310` y `DOCUMENTOS_CLAVE` con 32 bytes aleatorios en hexadecimal. Para otros entornos, el contenedor de ClamAV y el backend necesitan comunicación privada.

1. Abrir la ficha, subir un PDF y una imagen, comprobar la vista y descargar. Reemplazar el PDF y volver a consultar la versión anterior.
2. Repetir la carga por API con un archivo de 6 MiB y un archivo de tipo no permitido. Comprobar el código y que no se creó un archivo en SQL ni en MongoDB. Probar la acción de lectura con análisis pendiente y rechazado.
3. Abrir el archivo con una sesión sin acceso a archivos y verificar el `403` y la bitácora. Con acceso, verificar `CLI_ARCHIVO_VISTO` en SeguridadDB. Pedir el archivo bajo otra ficha y comprobar el `404`.
4. Detener MongoDB local para comprobar el `503` en alta y descarga mientras siguen visibles las demás secciones de la ficha. Restaurarlo y repetir. Detener ClamAV y comprobar que una carga válida queda sin confirmar y puede reintentarse.
5. Ejecutar `python -m app.core.tareas ejecutar CLI_ARCHIVOS_HUERFANOS` con un objeto ficticio de Clientes sin metadatos que supere las 24 horas. Confirmar que se conserva una versión histórica referenciada y que repetir la tarea no elimina archivos adicionales. El despliegue debe programar la tarea con el ejecutor de Enquo y preparar el índice de MongoDB `{origen: 1, creadoEn: 1}` para esta consulta.

## Contrato acordado con #39 y #387

- **#39 · Alta.** Los adjuntos temporales quedan asociados al identificador estable del trámite y al asesor. La confirmación valida titularidad del trámite, clase y estado limpio. Usa una transacción SQL para crear la ficha Pendiente y asociar el consentimiento, la evidencia de representación cuando corresponda y sus referencias digitales. Una reversión conserva los adjuntos disponibles para reintentar. Si la confirmación se guardó y se perdió la respuesta, repetir con el mismo identificador devuelve el mismo `idCliente`. Un mismo PDF puede respaldar varias constancias con el mismo `idArchivo`.
- **#387 · Relaciones.** `idArchivoSoporteAlta` usa `Clientes.ClienteRelacion.IdArchivoSoporte`. `idArchivoSoporteFin` se guarda por separado. Cada acto y cada versión del historial conserva su ID y la referencia descriptiva. Verificar el ID exacto con la ficha titular y el estado limpio en la transacción de la relación. En un relevo se verifica el respaldo de cada acto. Al vincular el respaldo del tutor vigente, la relación debe volver a evaluar `activar_si_cumple` antes de confirmar.
- **Habilitación.** `CLI_EXIGE_ARCHIVOS` controla el expediente digital. Natural con cédula exige anverso, reverso y consentimiento. Si su documento principal es pasaporte, `PASAPORTE_DATOS` sustituye las dos caras y se conserva el consentimiento. Jurídica exige RUC, nombramiento y consentimiento. Un menor requiere desde el alta la constancia del respaldo del tutor revisado. La habilitación con la bandera activa exige evidencia limpia vinculada al tutor vigente. Un archivo suelto en la ficha no acredita esa relación. La clase `RESPALDO_TUTOR` permite identificar el respaldo en la ficha. Para una persona natural sin fecha de nacimiento, se debe completar ese dato para determinar si requiere tutor.

La página de datos es la unidad de evidencia que describe el [Doc 9303 de OACI, parte 4 §4](https://www.icao.int/publications/documents/9303_p4_cons_en.pdf). La [resolución SEPS 2026-0119, art. 53](https://www.seps.gob.ec/wp-content/uploads/RESOLUCIO%CC%81N-Nro.-SEPS-IGT-IGS-IGJ-INR-INSESF-INGINT-2026-0119-signed.pdf) sustenta la verificación y conservación de evidencia de representación antes de operar según el flujo de Enquo. Las clases y el momento de su exigencia digital son decisiones del producto. El análisis de seguridad determina si el archivo se puede manejar. El asesor verifica el documento y las facultades de representación.

La habilitación y el catálogo ya aplican estas condiciones en el #389. La captura temporal y la confirmación idempotente necesitan el consumidor #39. El alta, fin e historial de relaciones necesitan el consumidor #387. Como prueba conjunta, confirmar una empresa con dos constancias que comparten PDF, perder la respuesta y reintentar. Repetir con fallo antes del commit. Verificar que cada escenario deje una sola ficha, que se rechacen archivos de otra ficha y archivos pendientes, y que sustituir el PDF conserve el respaldo histórico.
