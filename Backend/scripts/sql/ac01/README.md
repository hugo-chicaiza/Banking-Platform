# AC-01 y G-06

En CooperativaDB de prueba, aplicar las dos migraciones AC-01 en orden. Con
`Contabilidad.ElementoCUC` ya inicializado y antes de generar los asientos y
movimientos seed, ejecutar:

1. `001_catalogo_segmento_1.sql` carga 1.182 cuentas del CUC de octubre de 2023
   y tres cuentas internas de Efectivo. Resuelve las cuentas superiores por
   código. Reutiliza los IDs existentes, conserva los saldos y detiene la
   carga si una cuenta con saldo o movimientos necesita reclasificarse.
2. `002_plantillas_iniciales.sql` carga depósito en ventanilla, retiro en
   ventanilla y retiro ATM. Busca las cuentas por código y usa los tipos 3, 4 y
   16 del histórico. Confirmar esos tipos en el ambiente de prueba.

Si la BD de prueba contiene asientos seed que utilizan cuentas que pasarán a
ser agrupadoras, regenerarla desde su esquema y catálogos iniciales. Volver a
cargar esos asientos con los códigos imputables correspondientes, resolviendo
sus IDs por `CodigoCuenta`. El repositorio carece del script original de esos
asientos y movimientos.

## Clasificación de la semilla

- Activo y gastos son deudores. Pasivo, patrimonio e ingresos son acreedores.
  Las pérdidas de patrimonio `3602` y `3604` se cargan como deudoras.
- Las cuentas de valuación del activo y sus descendientes son acreedoras. Se
  identifican por la terminación `99` en el nivel de cuenta o subcuenta, según
  la sección 3 del marco conceptual del CUC. Las pérdidas de patrimonio
  conservan `EsCuentaValuacion = 0`.
- En contingentes y cuentas de orden, `61`, `63`, `71` y `73` son deudoras,
  mientras `62`, `64`, `72` y `74` son acreedoras. Las raíces `6` y `7`
  llevan naturaleza deudora como valor técnico de cuentas agrupadoras.
- Para las cuentas de saldo variable, la semilla conserva la naturaleza del
  elemento. `1908` queda deudora y `59` acreedora. La dinámica del CUC admite
  saldo deudor o acreedor para ambas.
- Una cuenta es imputable si no tiene hijos en el catálogo cargado. Esto
  incluye `59`, que tiene movimientos de cierre en la dinámica del CUC. La
  imputabilidad es una regla de la aplicación y el nivel de reporte a la SEPS
  se rige por la sección 10.4 del CUC.
- `110105` queda agrupadora y sus tres cuentas internas imputables son
  `11010501` bóveda, `11010502` caja y `11010503` ATM. Los códigos internos
  fueron asignados para la semilla del proyecto.

El CSV conserva los códigos, los nombres y la jerarquía oficial de SEG 1.
Las cuentas internas se agregan en la semilla SQL.

## Integración AC-01

Los módulos llaman a `generar_asiento` con la conexión de su transacción y
una clave estable del evento, como `TRANSACCION:123` o `DOTACION_CAJA:123`.
La unicidad del asiento complementa la idempotencia de la operación completa.
Quedan por configurar traslados, ajustes y las cuentas de crédito por
producto y rubro, además de integrar los módulos y el flujo de reverso.
Validar los scripts y la concurrencia en SQL Server antes de habilitar el
flujo en la aplicación.
