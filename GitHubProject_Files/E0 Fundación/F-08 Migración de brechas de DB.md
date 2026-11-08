---
number: 108
title: "F-08 | Migración de brechas de DB"
type: task
code: F-08
parent: "[[E0 Fundación]]"
status: Backlog
priority: P1
size: M
estimate: 3
estimate_be: 3
estimate_fe: 
etapa: "1-2"
start_date: 2026-10-19
target_date: 2026-11-04
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/108
---

> Como **equipo**, quiero **aplicar las brechas de DB aprobadas** para **que las historias tengan las tablas y columnas que necesitan**.

**Etapa:** 1-2 · **QA:** 0 d · **Tablas:** ver tabla

## Criterios de aceptación

- [ ] El grupo cierra las brechas en amarillo
- [ ] Script de migración versionado con su script de reversión, solo con brechas aprobadas
- [ ] Probado en una copia antes del entorno compartido
- [ ] Diccionario de Datos actualizado
- [ ] Cada historia afectada recibe un comentario con el cambio aplicado

## Reglas de negocio

| Decisión | Brechas | Historias |
|---|---|---|
| Aplicar | G-02 hash/intentos de PIN · G-05 estado del crédito · G-08 casete de depósito ATM · G-09 flujo de cuadre · G-10 pago de cuota sin cuenta · G-13 fecha contable tras corte | A-05, T-01, T-06, CR-05, CR-07, CR-08, T-04, T-10, CJ-03, CJ-04, CJ-06, CR-06, AC-02 |
| Decidir en grupo | G-06 plantillas de asiento · G-07 conciliación persistida · G-12 claves de política · G-16 retenciones | AC-01, CJ-05, CR-02, F-07, A-02 |
| Descartar | G-01 (la autenticación vive en SeguridadDB) · G-03 · G-04 · G-11 · G-14 · G-15 · G-17 | — |

## Dependencias

- Bloquea: F-07 y las historias de la tabla

## Pendiente

- Decidir G-06, G-07, G-12 y G-16.
- Vínculo con WorkOS (aplicado a mano el 2026-11-07, falta en esta migración):
  - `SeguridadDB.Organizacion.Usuarios.KeyUsuario varchar(64) NULL` con índice único filtrado `UX_Usuarios_KeyUsuario` (`WHERE KeyUsuario IS NOT NULL`): id del usuario en WorkOS.
  - `CooperativaDB.Organizacion.Agencia.KeyAgencia varchar(64) NULL` con índice único filtrado `UX_Agencia_KeyAgencia`: id de la organización en WorkOS.
  - `UsuarioID` e `IdAgencia` no cambian; los ids de WorkOS son los del entorno de producción.
  - `SeguridadDB.Organizacion.Usuarios.RolesWorkOS varchar(200) NULL` y `SeguridadDB.Auditoria.Auditoria.RolesWorkOS varchar(200) NULL`: roles que dio WorkOS, para comparar con `Seguridad.GruposUsuarios` (no se validan).
- G-02 (rediseñado 2026-11-07, TAR-05 con IBM 3624 PIN Offset): `SeguridadDB.Tarjetas.TarjetaPIN` guarda el Offset en `PINOffset varchar(4)` (ya existía) y la referencia de la PVK en `ReferenciaClavePVK varchar(32) NULL` (agregada a mano). Una asignación pendiente queda con `TienePINAsignado = 0` y `Estado = 'Inactivo'`; confirmada, `1` y `'Activo'`. `HashPIN` (Argon2id) deja de usarse y se elimina tras desplegar el código nuevo.
- Repositorio aislado de PAN ficticios (TAR-01, solo desarrollo y pruebas, agregado a mano 2026-11-07): esquema `SeguridadDB.Pruebas` y tabla `Pruebas.PanFicticio (IdTarjeta int PK, PanCifrado varbinary(64), ReferenciaClave varchar(32), FechaRegistro datetime2 DEFAULT SYSDATETIME())`. No debe crearse en producción. Ver `Backend/docs/HSM-Thales.md`.
- Contraseñas en WorkOS (aplicado a mano 2026-11-07): se eliminó `SeguridadDB.Organizacion.Usuarios.ClaveHash` (`varchar(256) NOT NULL`, sin índices ni restricciones; ningún código ni procedimiento la usaba).
  - Aplicar: `ALTER TABLE Organizacion.Usuarios DROP COLUMN ClaveHash;`
  - Reversión (los hashes anteriores no se recuperan): `ALTER TABLE Organizacion.Usuarios ADD ClaveHash varchar(256) NULL;`
  - Si se usan certificados, sus datos (huella SHA-256, serie, emisor, vigencia, estado) van en una tabla propia relacionada con `Organizacion.Usuarios`, no en esta columna.
- Estados de tarjeta y PIN temporal (A-05, aplicado a mano 2026-11-07):
  - `CooperativaDB.Tarjeta.Tarjeta.CK_Tarjeta_Estado` acepta solo `Solicitada`, `Aprobada`, `Generada`, `Activa`, `Inactiva`, `Bloqueada`, `Cancelada`, `Anulada`, `Vencida` y `Cerrada` (se quitan `EnRevision`, `Rechazada` y `Pendiente`). El valor por defecto sigue siendo `Solicitada`.
  - `Tarjeta.TarjetaHis.CK_TarjetaHis_Estados` con los mismos estados, creado `WITH NOCHECK` (el historial es inmutable: no se validan las filas existentes).
  - `Tarjeta.TransicionEstado`: se borran las filas con `EnRevision`, `Rechazada` o `Pendiente` y se agrega `Solicitada → Anulada` (rechazo). Quedan 17 transiciones (ver TAR-04).
  - `SeguridadDB.Tarjetas.TarjetaPIN.RequiereCambio bit NOT NULL` con `DF_TarjetaPIN_RequiereCambio DEFAULT 0`: 1 cuando el PIN es temporal (débito recién aprobada o PIN regenerado).
  - Un solo producto Tarjeta con subproductos (dato semilla, F-07): `ProductosFinancieros.Producto` 4 pasa de `TDB001` “Tarjeta de débito” a `TAR001` “Tarjeta”; sus subproductos son `TDB001-MC` “Débito Mastercard clásica” (BIN `500000`) y el nuevo `TCR001-MC` “Crédito Mastercard clásica” con el nuevo `Tarjeta.BIN` `510000` (ficticio, red Mastercard `IdRed = 2`). Débito o crédito lo define el subproducto: no hay columna nueva. Reversión: borrar el subproducto `TCR001-MC` y el BIN `510000` si no tienen tarjetas, y devolver el producto 4 a `TDB001` “Tarjeta de débito”.
  - Tarjetas semilla 1, 3 y 4 canceladas (`Activa → Cancelada`, con historial) y reemplazadas por tarjetas emitidas con el flujo real (TAR-01 y TAR-04, PIN generado por el HSM): no se borran porque tienen transacciones e historial inmutable.
  - Reversión: recrear `CK_Tarjeta_Estado` y `CK_TarjetaHis_Estados` con los 13 estados anteriores, borrar `Solicitada → Anulada`, volver a insertar `Solicitada → EnRevision`, `Solicitada → Rechazada`, `EnRevision → Aprobada`, `EnRevision → Rechazada`, `Generada → Pendiente`, `Pendiente → Activa` y `Pendiente → Anulada`, y `ALTER TABLE Tarjetas.TarjetaPIN DROP CONSTRAINT DF_TarjetaPIN_RequiereCambio, COLUMN RequiereCambio;`.
