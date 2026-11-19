# E2-03 Importar un catálogo

Rutas bajo el prefijo API de contabilidad. Requieren `con-cuenta-editar` y
una identidad interna. La importación corresponde al usuario que la cargó.

- `POST /contabilidad/cuentas/importaciones` recibe el CSV como cuerpo
  `text/csv` y el nombre en `X-Nombre-Archivo`. Devuelve 201 con el ID, los
  conteos y la revisión. Formato UTF-8, con BOM opcional, hasta 2 MiB y 5.000
  registros como tope de seguridad. `CON_IMPORTACION_MAX_FILAS` permite reducir
  el limite global. Cabecera exacta
  `CodigoCuenta,NombreCuenta,CodigoCuentaSuperior,Naturaleza`.
- `GET /contabilidad/cuentas/importaciones/{id}` devuelve la revisión
  persistida. `numeroFila` indica la línea física inicial del registro.
- `POST /contabilidad/cuentas/importaciones/{id}/aplicar` revalida contra
  el catálogo actual y confirma el cambio con el actor y la fecha en la
  misma transacción. Si cambia la clasificación de una fila, se solicita
  cargar y revisar nuevamente. El mismo ID aplicado devuelve el resultado.

Los niveles admitidos son 1, 2, 4 y 6. En una raíz el padre va vacío. La
naturaleza es DEUDORA o ACREEDORA. Se bloquea alterar naturaleza con uso o
desactivar imputabilidad de cuentas con saldo o movimientos mediante importación.
Instalar la migración después del esquema E2-01. El catálogo AC-01 de tres
columnas requiere agregar naturaleza según la clasificación oficial revisada.
El mantenimiento #206 conserva 501 en las operaciones sujetas a aprobación. Queda pendiente
compartir la validación con su implementación y conectar una interfaz de usuario.

Prueba local: desde Backend, con PYTHONPATH apuntando a Backend, ejecute
tests/integration/e203_sql_lab.py con el nombre de la base de ensayo E2-01.
El ensayo verifica instalación repetida, reaplicación y rechazo de una
revisión obsoleta cuando cambia la cuenta.

Dentro del alcance de #206 se habilita el cambio de nombre de auxiliares
por PATCH /contabilidad/cuentas-contables/{idCuentaContable}, con identidad
interna y auditoría. El catálogo regulatorio se edita por importación.
Altas, cambios de estado y bajas del mantenimiento requieren la cola de
aprobación. La política de niveles debe aclarar el ejemplo 210140 de #206,
que tiene seis dígitos y se solapa con los niveles reservados al regulador.

La semilla opcional `202611191500_importacion_limite_filas.up.sql` se aplica
en CooperativaDB despues de E0-09 y conserva valores existentes. Sin parametro
vigente la API conserva el limite anterior de 5.000. El alineamiento con E2-02
queda sujeto a la definicion de los cambios de naturaleza y jerarquia que se
admitiran en mantenimiento ordinario.
