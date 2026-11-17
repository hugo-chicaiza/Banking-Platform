# E2-03 Importar un catálogo

Rutas bajo el prefijo API de contabilidad. Requieren `con-cuenta-editar` y
una identidad interna. La importación corresponde al usuario que la cargó.

- `POST /contabilidad/cuentas/importaciones` recibe el CSV como cuerpo
  `text/csv` y el nombre en `X-Nombre-Archivo`. Devuelve 201 con el ID, los
  conteos y la revisión. Formato UTF-8, con BOM opcional, hasta 2 MiB y 5.000
  registros. Cabecera exacta
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
El contrato de mantenimiento #206 en develop responde 501. Queda pendiente
compartir la validación con su implementación y conectar una interfaz de usuario.

Prueba local: desde Backend, con PYTHONPATH apuntando a Backend, ejecute
tests/integration/e203_sql_lab.py con el nombre de la base de ensayo E2-01.
El ensayo verifica instalación repetida, reaplicación y rechazo de una
revisión obsoleta cuando cambia la cuenta.
