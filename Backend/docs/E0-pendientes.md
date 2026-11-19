# E0 · Pendientes de ejecución, activación y ajustes

Estado al 2026-11-19. Lista de lo que falta **ejecutar, activar o modificar** de cada E0 desarrollado en esta fase.
El código de todos está en `develop`. Lo que se despliega desde `develop` llega al App Service de desarrollo
(`develop_backend-dev.yml`). Para llegar al App Service principal se pasa a `main` (`main_backend.yml`) con un PR
`develop → main` y una aprobación.

Pasos de Azure: [E0-azure.md](E0-azure.md). Qué hace cada E0: [E0-resumen.md](E0-resumen.md).
Secretos locales (frase de cifrado): `.env.secretos` en la raíz del repositorio, ignorado por Git.

## Resumen

| E0 | Qué es | Estado | Lo que falta |
|---|---|---|---|
| E0-01 | Migraciones versionadas | Código listo, **apagado** | Pasar a `main`, generar la línea base, comprobarla en una base vacía, marcarla y activar |
| E0-02 | Respaldo y restauración | Código listo, **bloqueado por Azure** | Credencial federada, workflows en `main`, primer respaldo y prueba de restauración |
| E0-03 | Contrato de la API | Código listo, **apagado** | Decidir la activación: comparación del contrato en el pipeline y uso en el frontend |
| E0-05 | Auditoría con bandeja | **Activo en la base** (migraciones aplicadas) | Mergear #495, pasar a `main`, alertas en Azure; ATM al activarse |
| E0-06 | Tareas programadas | **Activo en la base** | Pasar a `main` (activa los web jobs), comprobar ejecuciones, alerta en Azure |
| E0-11 | Pipeline y ramas | Activo en el backend | Reglas de la rama `master` del frontend (responsable del repositorio frontend) |
| E0-13 | Registros | Activo | Opcional: `LOG_FORMATO=json` y retención de registros en App Service |
| E0-16 | Inventarios de seguridad | Documentado | Capacitaciones formales y revisión al cierre de fase |
| E0-18 | Documentos PDF | Activo | Nada pendiente |
| Transversal | | | Rotar secretos compartidos, login de la app con menos privilegios, cerrar los issues |

---

## E0-01 · Migraciones versionadas
Código: `app/core/migraciones/`, `scripts/generar_linea_base.py`. Guía completa: [E0-01-migraciones.md](E0-01-migraciones.md).
F-08 (brechas de la base) **no** se aplica, por decisión.

- [ ] **Pasar a `main`** (PR `develop → main`).
- [ ] **Login administrativo para migrar.** Guardar `MIGRACIONES_ODBC_COOPERATIVA` y `MIGRACIONES_ODBC_SEGURIDAD`
      como secretos de quien ejecuta, nunca en el App Service. Sirve el administrador del servidor o uno propio.
- [ ] **Generar la línea base** de cada base (`000000000000_linea_base.up.sql`) y revisarla.
- [ ] **Comprobarla en una base vacía** (Azure SQL gratuita o SQL Server en Docker): aplicar la línea base y
      comparar la estructura con la compartida.
- [ ] **Marcarla** en la base compartida sin ejecutarla: `aplicar --marcar-linea-base`.
- [ ] **Registrar como aplicadas las migraciones que ya se corrieron a mano**, para que el ejecutor no las repita:
      | Base | Migraciones aplicadas a mano |
      |---|---|
      | SeguridadDB | `202611191000_auditoria_formato`, `202611191100_auditoria_evento_relevo`, `202611191200_tareas_programadas`, `202611191310_auditoria_eventos_ventanilla`, `202611191400_auditoria_eventos_atm` y las de E0-08 (`202611180800…180805`) |
      | CooperativaDB | `202611172000…172002` (parámetros), `202611180802` (aprobaciones), `202611181010…181011` (agencias) |
      Todas son repetibles (`MERGE`, `IF NOT EXISTS`), pero no deben quedar fuera de `Migracion.Bitacora`.
- [ ] **Activar**: `MIGRACIONES_HABILITADAS=true` solo donde se ejecuten migraciones.

## E0-02 · Respaldo y restauración
Workflows: `respaldo-bd.yml` (diario, cifrado), `restaurar-bd.yml` (manual) y `ensayo-migraciones.yml` (apagado).
Destino: Backblaze B2, bucket `enquo-respaldos-coop`. Guía: [E0-02-respaldos.md](E0-02-respaldos.md).

- [ ] **Azure, en la identidad `backend-dev-id-bf29`**:
  - [ ] Confirmar la asignación del rol «Colaborador de SQL Server» sobre el servidor `enquohub` (la captura estaba
        en el paso «Miembros»; falta «Revisar y asignar»).
  - [ ] Agregar la **credencial federada**: GitHub Actions, organización `hugo-chicaiza`, repositorio
        `Banking-Platform`, entidad **Environment**, nombre `respaldos`.
- [ ] **Pasar los workflows a `main`.** GitHub solo programa y lanza a mano los workflows de la rama por defecto.
- [ ] **Primer respaldo**: lanzar `respaldo-bd.yml` a mano y confirmar el archivo cifrado en B2.
- [ ] **Prueba de restauración**: `restaurar-bd.yml` hacia una base temporal; anotar fecha, duración y resultado en
      `E0-02-respaldos.md`.
- [ ] Opcional: ensayo de migraciones (`ENSAYO_MIGRACIONES=true`) cuando E0-01 esté activo.

## E0-03 · Contrato de la API
Código: `scripts/contrato.py` (exportar, comparar, convenciones), `Backend/contract/*.json` (18 módulos); en el
frontend, `contrato-ejemplo.ts`, la simulación y `npm run contrato:tipos`.

- [ ] Decidir la activación. Si se activa:
  - [ ] Agregar `python scripts/contrato.py comparar` al pipeline del backend: falla si el código cambió el contrato
        sin actualizar `contract/`.
  - [ ] Usar en el frontend los tipos generados (`contrato:tipos`) y la simulación (`dev:contrato`) para las
        pantallas nuevas.
  - [ ] Acordar la regla: el contrato se actualiza como primera tarea de cada historia y lo revisan backend y frontend.

## E0-05 · Auditoría con bandeja de salida
Base: formato nuevo, catálogo `Auditoria.TipoEvento` (68 eventos) y la bitácora protegida contra cambios y borrados,
**ya aplicados** en SeguridadDB. Código: #492 (parte A, mergeado) y **#495** (parte B, abierto).

- [ ] **Mergear #495** y pasar a `main`.
- [ ] **Alertas en Azure Monitor** sobre los registros del App Service (nivel ERROR):
  - `AUD_RELEVO_ALERTA`: un evento lleva más de 10 minutos sin pasar a la bitácora.
  - `TAREA_SIN_EJECUTAR` (E0-06).
- [ ] Opcional: `AUD_RELEVO_ALERTA_MINUTOS` en el App Service solo si se quiere un valor distinto de 10.
- [ ] **ATM** (cuando se habiliten retiro, transferencia, reverso o depósito): llamar
      `atm.auditoria.confirmar_atm(...)` dentro de la transacción de cada operación. Los eventos ya están en el
      catálogo. La prueba `test_atm_al_activarse_exige_evento_en_la_transaccion` falla si se activa una sin hacerlo.
- [ ] **Al habilitar una operación de dinero nueva**: `auditar(...)` + `registro.confirmar(conn)` dentro de su
      `with conn.begin()`, y su código en el catálogo por migración. Las pruebas del pipeline lo exigen.
- [ ] Revisar más adelante (fuera de E0-05): en `caja/repository.py`, los totales del cuadre filtran por
      `TipoTransaccion = 'Deposito' | 'Retiro' | 'Pago_Credito'` escritos en el SQL. Si se agregan tipos nuevos,
      conviene agruparlos por la naturaleza de `Transacciones.TipoTransaccion` o de `Caja.TipoMovimientoCaja`.

## E0-06 · Tareas programadas
Base: `Sistema.Tarea` con ventana esperada y las tareas `ATM06_RECUPERACION` y `SIS_VIGILANTE`, **ya aplicado**.
Código: `app/core/tareas/`, web jobs `atm06-recovery` (migrado al ejecutor) y `sis-vigilante` (nuevo).
Guía: [E0-06-tareas.md](E0-06-tareas.md).

- [ ] **Desplegar** (`develop` → App Service de desarrollo; luego `main`). Los web jobs se activan con el despliegue.
- [ ] **Comprobar** en `Sistema.TareaEjecucion` que `ATM06_RECUPERACION` corre cada minuto y `SIS_VIGILANTE`
      cada 5 minutos. Hasta entonces, el vigilante reporta `ATM06_RECUPERACION` como atrasada.
- [ ] Confirmar en el portal de Azure (*WebJobs*) que ambos aparecen como *Triggered* y sin errores.
- [ ] Alerta `TAREA_SIN_EJECUTAR` en Azure Monitor (ver E0-05).

## E0-11 · Pipeline y protección de ramas
- [x] Backend `develop`: check obligatorio «Backend Quality and Security», sin revisión obligatoria.
- [x] Backend `main`: check «Origen del pull request hacia main» y una aprobación.
- [ ] **Frontend `master`** (responsable del repositorio frontend):
  - [ ] Cambiar el check obligatorio «SonarQube Code Analysis» por **«SonarCloud Code Analysis»**, que es el nombre
        real; con el nombre equivocado ningún PR puede cumplirlo.
  - [ ] Agregar un workflow de origen como `pr-a-main.yml` del backend (solo `develop` → `master`) y exigirlo.

## E0-13 · Registros
- [x] Enmascarado de tarjetas, tokens y secretos; sin query string; inventario en
      [inventario-registros.md](inventario-registros.md).
- [ ] Opcional: `LOG_FORMATO=json` en el App Service si se van a consultar los registros con Log Analytics.
- [ ] Fijar la retención de *App Service logs* (recomendado: 30 días).

## E0-16 · Inventarios de seguridad
- [ ] **Capacitaciones formales** ([07-gobierno.md](seguridad/07-gobierno.md)): ASVS y PCI (Matthew), LOPDP e IA
      (Eli). Registrar fecha, duración y certificado de cada una.
- [ ] **Revisión al cierre de cada fase**: inventarios 01–03, vulnerabilidades abiertas, modelos de amenazas.

## E0-18 · Documentos PDF
- [x] Generador activo. Sin pendientes.

## Transversales
- [ ] **Rotar los secretos compartidos en el chat**: la llave de aplicación de Backblaze B2 (`B2_APP_KEY`) y la
      frase de cifrado de los respaldos (`BACKUP_PASSPHRASE`). Antes de cambiar la frase, guardar la anterior
      fuera del repositorio: hace falta para restaurar los respaldos hechos con ella.
- [ ] **Login de la aplicación con menos privilegios**: hoy `devcat` es administrador del servidor y `db_owner` de
      las dos bases. La app debería usar un login solo con los permisos que necesita; el administrador queda para
      migraciones y emergencias.
- [ ] **Cerrar en GitHub los issues entregados**: E0-03, E0-05, E0-06, E0-11, E0-13, E0-16 y E0-18. Los PR los
      mencionan sin cerrarlos. E0-01 y E0-02 quedan abiertos hasta terminar lo de arriba.
