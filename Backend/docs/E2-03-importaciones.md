# E2-03 #372 · Importar el catálogo del regulador

## Autorización

Las tres rutas requieren una sesión WorkOS válida, un usuario activo vinculado a una identidad interna y acceso a Contabilidad. Con el modelo de permisos WorkOS se requiere `con-cuenta-editar`. Cuando está activo el modelo de funciones SQL, se verifica la función asignada a la operación concreta. Consulta y aplicación quedan restringidas al usuario interno que cargó el archivo.

| Método y ruta | Función SQL | Solicitud | Éxito |
| --- | --- | --- | --- |
| `POST /api/v1/contabilidad/cuentas/importaciones` | `contabilidad.importaciones.preparar` | Cuerpo CSV y encabezados descritos abajo | `201` con la revisión persistida, incluso si tiene errores por fila |
| `GET /api/v1/contabilidad/cuentas/importaciones/{id}` | `contabilidad.importaciones.consultar` | ID numérico de la carga en la ruta, sin cuerpo | `200` con la revisión y el estado persistidos |
| `POST /api/v1/contabilidad/cuentas/importaciones/{id}/aplicar` | `contabilidad.importaciones.aplicar` | ID numérico de la carga en la ruta, sin cuerpo | `200` con la revisión aplicada, incluido un reintento del mismo ID |

No se requieren parámetros de consulta. El ID debe estar entre 1 y 2.147.483.647.

## Solicitud de carga

Enviar los bytes del archivo directamente en el cuerpo, con `Content-Type: text/csv` y `X-Nombre-Archivo: catalogo-seps.csv`. Se admite UTF-8 con BOM opcional, un nombre de hasta 200 caracteres con extensión `.csv` y un máximo de 2 MiB. El CSV debe contener al menos un registro. El límite efectivo de registros es el menor entre 5.000 y el valor global vigente de `CON_IMPORTACION_MAX_FILAS` en CooperativaDB. Si falta un valor vigente se usa el tope de 5.000.

La cabecera es exacta y se respetan el orden y la cantidad de columnas. Enviar los códigos como texto para conservar ceros iniciales.

```csv
CodigoCuenta,NombreCuenta,CodigoCuentaSuperior,Naturaleza
110197,Efectivo en tránsito,1101,DEUDORA
```

## Respuestas de éxito

Las tres respuestas JSON comparten la misma estructura. Los nombres de campo distinguen mayúsculas y minúsculas. Las fechas son UTC y se serializan sin sufijo de zona. `CargadoPor` y `AplicadoPor` son IDs internos numéricos. `AplicadoPor` y `FechaAplicada` son `null` mientras el estado sea `Revision`.

La suma de `FilasNuevas`, `FilasCambiadas`, `FilasIguales` y `FilasError` equivale a `Filas`. La revisión conserva el orden del CSV. `numeroFila` es la línea física donde comienza el registro y la cabecera ocupa la línea 1. `resultado` admite `Nueva`, `Cambiada`, `Igual` y `Error`. `codigoError` es `null` para filas válidas y `anterior` es `null` cuando el código no existe en el plan.

### Carga · 201

```json
{
  "IdImportacion": 372,
  "NombreArchivo": "catalogo-seps.csv",
  "Filas": 1,
  "FilasError": 0,
  "FilasNuevas": 0,
  "FilasCambiadas": 1,
  "FilasIguales": 0,
  "CargadoPor": 101,
  "FechaCarga": "2026-11-19T14:02:19.420000",
  "AplicadoPor": null,
  "FechaAplicada": null,
  "estado": "Revision",
  "revision": [
    {
      "numeroFila": 2,
      "CodigoCuenta": "110197",
      "NombreCuenta": "Efectivo en tránsito",
      "CodigoCuentaSuperior": "1101",
      "Naturaleza": "DEUDORA",
      "resultado": "Cambiada",
      "codigoError": null,
      "anterior": {
        "nombre": "Efectivo por trasladar",
        "naturaleza": "DEUDORA",
        "padre": "1101",
        "regulador": true,
        "imputable": false
      }
    }
  ]
}
```

### Consulta · 200

Ejemplo de una revisión bloqueada. El estado sigue siendo `Revision` y `FilasError` determina si se puede solicitar la aplicación.

```json
{
  "IdImportacion": 373,
  "NombreArchivo": "catalogo-corregir.csv",
  "Filas": 1,
  "FilasError": 1,
  "FilasNuevas": 0,
  "FilasCambiadas": 0,
  "FilasIguales": 0,
  "CargadoPor": 101,
  "FechaCarga": "2026-11-19T14:03:11.123000",
  "AplicadoPor": null,
  "FechaAplicada": null,
  "estado": "Revision",
  "revision": [
    {
      "numeroFila": 2,
      "CodigoCuenta": "110198",
      "NombreCuenta": "Fondos en tránsito",
      "CodigoCuentaSuperior": "1102",
      "Naturaleza": "DEUDORA",
      "resultado": "Error",
      "codigoError": "CODIGO_NO_CORRESPONDE_AL_PADRE",
      "anterior": null
    }
  ]
}
```

### Aplicación · 200

```json
{
  "IdImportacion": 372,
  "NombreArchivo": "catalogo-seps.csv",
  "Filas": 1,
  "FilasError": 0,
  "FilasNuevas": 0,
  "FilasCambiadas": 1,
  "FilasIguales": 0,
  "CargadoPor": 101,
  "FechaCarga": "2026-11-19T14:02:19.420000",
  "AplicadoPor": 101,
  "FechaAplicada": "2026-11-19T14:05:31.810000",
  "estado": "Aplicada",
  "revision": [
    {
      "numeroFila": 2,
      "CodigoCuenta": "110197",
      "NombreCuenta": "Efectivo en tránsito",
      "CodigoCuentaSuperior": "1101",
      "Naturaleza": "DEUDORA",
      "resultado": "Cambiada",
      "codigoError": null,
      "anterior": {
        "nombre": "Efectivo por trasladar",
        "naturaleza": "DEUDORA",
        "padre": "1101",
        "regulador": true,
        "imputable": false
      }
    }
  ]
}
```

## Respuestas de error

| Ruta | HTTP | Código y condición |
| --- | --- | --- |
| Carga | 422 | `ARCHIVO_INVALIDO` por formato, cabecera, cantidad de columnas, codificación, nombre, ausencia de registros o exceso de tamaño o filas |
| Carga | 422 o 503 | La validación compartida del parámetro puede devolver `TIPO_PARAMETRO_INVALIDO`, `VALOR_FUERA_DE_RANGO` o `VALOR_NO_PERMITIDO` con 422. Si el valor resuelto no es un entero positivo, devuelve `503 LIMITE_IMPORTACION_INVALIDO` |
| Consulta y aplicación | 400 | `DATOS_INVALIDOS` si el ID de la ruta es inválido |
| Consulta y aplicación | 404 | `IMPORTACION_NO_ENCONTRADA` si el ID no existe o pertenece a otro usuario |
| Aplicación | 422 | `IMPORTACION_CON_ERRORES` si la revisión guardada tiene filas bloqueantes |
| Aplicación | 409 | `CATALOGO_CAMBIO` si la revisión recalculada difiere de la presentada originalmente |
| Las tres | 401 | Sesión ausente, inválida o vencida. La capa de autenticación indica el motivo en `code` |
| Las tres | 403 | Identidad interna, sección o permiso no habilitado. Ejemplos: `USUARIO_NO_REGISTRADO`, `ACCESO_SECCION_RETIRADO`, `SIN_PERMISO` y `FUNCION_NO_AUTORIZADA` |
| Las tres | 429, 500 o 503 | Errores de plataforma, entre ellos límite de peticiones, fallo interno y servicio no disponible |

Los errores de ruta se devuelven como `application/problem+json` con un mensaje público y un `traceId` para soporte. En errores de validación puede aparecer `errors`. La traducción común de errores SQL devuelve mensajes públicos y puede devolver códigos de restricciones de negocio. El cliente puede usar el estado HTTP y el mensaje público si recibe un código desconocido.

```json
{
  "type": "about:blank",
  "title": "Conflict",
  "status": 409,
  "code": "CATALOGO_CAMBIO",
  "detail": "Cargue el archivo de nuevo para revisar el catálogo actual.",
  "traceId": "b2c7530a-4fae-4bf1-ad71-71366acdcfa0"
}
```

### Motivos de fila

| `codigoError` | Motivo que puede mostrar el cliente |
| --- | --- |
| `CODIGO_INVALIDO` | El código debe contener 1, 2, 4 o 6 dígitos. Los auxiliares de 8 dígitos están fuera de la importación |
| `CODIGO_DUPLICADO` | El código aparece más de una vez en el CSV |
| `CODIGO_NO_CORRESPONDE_AL_PADRE` | El padre no coincide con el prefijo exigido o no existe en el catálogo ni entre las filas válidas del CSV. En cuentas raíz, el padre debe ir vacío |
| `DATOS_INVALIDOS` | El nombre está vacío, excede el límite o no se puede almacenar sin cambios, o la naturaleza difiere de `DEUDORA` y `ACREEDORA` |
| `NATURALEZA_EN_USO` | La cuenta tiene movimientos, saldo o cuentas hijas |
| `RECLASIFICACION_REQUERIDA` | La cuenta es imputable y tiene saldo o movimientos |

## Matriz de compatibilidad frontend/backend

| Necesidad | Datos y comportamiento |
| --- | --- |
| Mostrar nuevas, modificadas y sin cambios | Usar los tres contadores y filtrar `revision` por `Nueva`, `Cambiada` o `Igual` |
| Mostrar errores con fila y motivo | Mostrar `numeroFila` y traducir `codigoError` con la tabla anterior. El servidor devuelve un código por fila |
| Identificar bloqueos | Habilitar Aplicar cuando `estado === "Revision"` y `FilasError === 0`. El servidor también verifica el bloqueo |
| Previsualizar diferencias | Comparar `anterior.nombre`, `anterior.padre` y `anterior.naturaleza` con `NombreCuenta`, `CodigoCuentaSuperior` y `Naturaleza`. Normalizar `null` y cadena vacía como padre ausente. Los valores propuestos para `regulador` e `imputable` son siempre `true` y `false` para filas aplicables |
| Consultar estado | Usar GET y leer `Revision` o `Aplicada` en `estado`. El bloqueo se obtiene con `FilasError`; la obsolescencia se conoce al intentar aplicar |
| Evitar aplicaciones duplicadas | Deshabilitar el botón mientras haya una petición activa. Si hay un timeout, consultar o reintentar con el mismo ID. Un ID aplicado conserva actor, fecha y resultados |
| Detectar revisión obsoleta | Ante `409 CATALOGO_CAMBIO`, solicitar una nueva carga y revisión |
| Mostrar resultado final | Usar los contadores, `AplicadoPor` y `FechaAplicada`. El contrato entrega el ID interno como identificación del usuario y no incluye su nombre visible |
| Actualizar el Plan de cuentas | Ante `200` con `estado: "Aplicada"`, invalidar la consulta local y volver a pedir `GET /api/v1/contabilidad/cuentas-contables`. La ruta requiere acceso de lectura a CON-03. Usar la consulta sin `imputable=true` para incluir las cuentas regulatorias. El Plan devuelve IDs y jerarquía definitivos |

## Consistencia y verificación

La aplicación bloquea la revisión por ID, recalcula las diferencias frente al catálogo dentro de la transacción y escribe los cambios junto con `AplicadoPor` y `FechaAplicada`. Crea padres antes que hijos. Las filas `Igual` se omiten. Una excepción revierte las escrituras. El evento de auditoría `CON_CATALOGO_IMPORTADO` vincula el intento con el usuario WorkOS y el ID de importación. La evidencia transaccional de la aplicación queda en el registro de importación.

El laboratorio `tests/integration/e203_sql_lab.py` usa una base local de ensayo E2-01 y verifica el flujo HTTP, propiedad y permisos simulados, identificación del actor en auditoría, redacción de errores SQL, rollback, concurrencia, revisión obsoleta y compatibilidad con el mantenimiento E2-02. El límite configurable se prueba en una base desechable con `tests/integration/test_parametros_migraciones_sql.py` y `E009_LOCAL_DDL=1`.
