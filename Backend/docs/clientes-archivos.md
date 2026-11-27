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

El enlace del alta de #39 requiere el contrato de referencias antes de que exista `idCliente`. El enlace de #387 requiere que las relaciones escriban y lean el `idArchivo` del respaldo correspondiente. El catálogo inicial usa las clases del issue. La regla de obligatoriedad durante el alta, incluida la de pasaporte, y la activación de `CLI_EXIGE_ARCHIVOS` se coordinan con esa integración.
