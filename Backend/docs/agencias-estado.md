# Estado de agencias

Fecha de revisión: 2026-11-12. Rama `feat/backend-agencias-estado`, sin número
porque este cambio aún no tiene issue. Base actualizada: `origin/develop`,
commit `8a9014e979aac5dc3344614aaa1eef48b17f1b52`.

## Separación del trabajo contable

La carpeta principal está en la rama de agencias. La rama
`feat/backend-65-ac01-plantillas` conserva sus cambios sin commit en el worktree
`.local-labs/ac01-pendiente`. Se verificaron contra el respaldo Git los contenidos
de sus 15 archivos modificados y 18 nuevos: sin diferencias. El respaldo stash
se conserva. El worktree está excluido localmente de Git para no incorporarlo
por accidente al cambio de agencias. La separación no modificó el historial de
AC-01. No se hizo push ni se abrió PR.

## Contrato y DDL

Se consultaron por SELECT los metadatos vigentes de `Organizacion.Agencia` en
`CooperativaDB` de Azure. `IdAgencia` es `char(3)`, `Estado` es `char(1)` y
`CK_Agencia_Estado` admite exactamente `A`, `I` y `C`; la restricción está habilitada
y es confiable. No hay migración ni cambio de DDL para este PATCH.

`PATCH /api/v1/agencias/{id_agencia}/estado` está en el módulo `organizacion`.
Requiere sesión y `require_roles("ADMIN")`. El body solo admite:

```json
{"estado": "I"}
```

Respuesta 200:

```json
{"idAgencia": "001", "estado": "I"}
```

| Transición | Resultado |
| --- | --- |
| A → I, I → A | 200; cambia solo `Agencia.Estado` |
| A → A, I → I, C → C | 200; sin UPDATE ni segunda escritura de auditoría |
| C → A, C → I | 409 `AGENCIA_CERRADA` |
| A → C, I → C | 409 `CIERRE_AGENCIA_NO_HABILITADO` |
| Agencia inexistente | 404 `AGENCIA_NO_ENCONTRADA` |
| Sin ADMIN | 403 `SIN_PERMISO` del control existente |
| Otro estado, body vacío o campos adicionales | 400 `DATOS_INVALIDOS` |

No se encontró requisito que defina el cierre A/I → C: queda fuera del PATCH.
No se eliminan ni desactivan usuarios, membresías WorkOS o asignaciones existentes.
Los cambios efectivos usan la auditoría best-effort existente, después del commit.
La repetición del estado no genera otra auditoría de cambio. El GET
`/api/v1/catalogos/agencias` se conserva con sus tres estados; no se duplicó ni movió.

## WorkOS y permisos

Se usó la configuración local `APP_ENV=staging` y sus credenciales actuales,
solo para lecturas. No se imprimieron claves, tokens, correos ni nombres de usuarios.

- Organización `Hgo`, vinculada en la base a agencia `002`: seis membresías activas,
  cinco con slug `admin` y una con `member`.
- El catálogo de roles del ambiente y los de las organizaciones visibles `Hgo`
  y `Test Organization` devuelven `admin` y `member`. No apareció `org-contador`
  como rol ni como organización, ni en las membresías consultadas.
- El vínculo WorkOS de agencia `001` apunta a una organización no visible con
  esta configuración. No se atribuye a un usuario/organización de prueba ni se
  presupone que el entorno del Dashboard sea el mismo. Debe revisarse ese vínculo
  y confirmar otra configuración si allí se esperaba `org-contador`.
- `normalizar_roles` convierte mayúsculas y guiones a `_` y acepta solo los
  nombres canónicos del backend. `admin` → `ADMIN`, `member` se ignora y
  `org-contador` se convertiría en `ORG_CONTADOR`, que se ignora. `contador` sí
  normaliza a `CONTADOR`, pero ese rol no tiene permiso para el PATCH.

No se añadieron aliases ni se ampliaron permisos. El backend declara más roles
que los presentes en el catálogo WorkOS visible; su configuración no se sincronizó.
`ADMIN` queda confirmado tanto en el catálogo como en membresías activas.
La lectura de roles personalizados siguió el [API oficial de WorkOS](https://workos.com/docs/reference/roles/custom-role),
porque el SDK instalado no expone esos métodos. No se crearon usuarios, roles,
membresías ni invitaciones.

## Alta y asignación: alcance real

La revisión de `Backend/app`, scripts y rutas no encontró un escritor de alta de
usuarios, invitaciones ni asignación de cajeros. Auth solo implementa AUT-01..04;
`_resolver_usuario` sincroniza `RolesWorkOS` del vínculo existente, no crea ni
asigna usuarios. El lector de `Caja.CajerosAsignadosAgencia` tampoco es un alta.

Los flujos están documentados en:

- `GitHubProject_Files/E1 Creación de usuarios-clientes/C-05 Crear usuarios del sistema, asignación de roles y cajer/AUT-06 POST usuarios.md`.
- La misma carpeta, `AUT-11 POST agencias-{idAgencia}-cajeros.md`.
- `AUT-08 PATCH usuarios-{idUsuario}.md` solo contempla nombre/email/estado, no
  asignación. No se modificó ese contrato.

Se agregó `organizacion.service.exigir_agencia_destino_activa(conn, id_agencia)`.
Exige transacción abierta, obtiene la agencia con `UPDLOCK,HOLDLOCK`, rechaza
I/C con 409 antes de permitir acciones posteriores y responde 404 si no existe.
El lock se conserva hasta el commit/rollback del llamador. El PATCH bloquea la
misma fila, evitando que se desactive entre validación y escritura local.

Punto de conexión de los futuros servicios, usando la conexión de CooperativaDB:

```python
with conn.begin():
    organizacion_service.exigir_agencia_destino_activa(conn, id_agencia)
    # Solo después: invitación/alta o membresía WorkOS y escritura de asignación.
    # Conservar el lock hasta terminar la escritura local.
```

AUT-06 debe resolver primero la agencia destino: su request documentado todavía
no incluye agencia/organización y mantiene pendientes de cédula y passwordTemporal.
Debe llamar al guard antes de cualquier alta o invitación WorkOS. AUT-11 debe
llamarlo antes de cerrar una asignación previa, crear la nueva o modificar una
membresía WorkOS. No se implementaron esos endpoints ni se pretendió que una
prueba del guard acreditara una alta real.

La futura orquestación debe coordinar sus efectos en WorkOS/SeguridadDB con la
persistencia local e idempotencia/recuperación: una transacción SQL no revierte
una invitación externa. Este cambio solo define y prueba el guard y su lock.

## Archivos y validación

- `Backend/app/modules/organizacion/{__init__,schemas,repository,service,router}.py`:
  DTO, acceso SQL, transiciones, guard de agencia activa y PATCH administrativo.
- `Backend/app/main.py`: registra el router.
- `Backend/tests/unit/test_agencias_estado.py`: HTTP, transiciones, no-op,
  roles/slugs, contrato estricto y composición simulada del guard antes de
  WorkOS/escritura para alta y asignación.
- `Backend/tests/unit/test_autorizacion.py`: incorpora la ruta a la matriz global.
- `Backend/tests/integration/test_agencias_estado_sql_lab.py`: estados y guard
  sobre SQL Server real, incluyendo dos conexiones concurrentes.

Resultados:

- 2.258 pruebas unitarias del backend aprobadas.
- 281 pruebas relacionadas de agencias, autorización y catálogos aprobadas.
- 14 pruebas SQL locales aprobadas. El guard mantiene bloqueado un UPDATE
  concurrente de estado (timeout 1222); después de terminar la transacción,
  el UPDATE sí puede ejecutarse. I/C impiden avanzar al guard; A lo permite.
- Los tests de alta/asignación usan WorkOS y persistencia simulados para comprobar
  el orden y que no son invocados en I/C; no existe todavía un flujo real que
  permita validación de extremo a extremo.
- Ruff format y format --check sobre los nueve archivos Python tocados, Ruff
  check y `git diff --check`, correctos.

La prueba SQL requiere `AGENCIAS_ESTADO_LOCAL_SQL_ENABLED=1` y está fijada a
`DESKTOP-OR5GE4R.CooperativaDB_AC01_Lab`; no carga `.env` ni permite cambiar el
destino. Crea una agencia `997` y ubicación ficticias propias, se niega a
sobrescribirlas si ya existen y las elimina al terminar. No toca tablas contables
ni datos WorkOS/Azure. El fixture se confirma solo para probar el bloqueo entre
conexiones y limpia explícitamente sus propias filas.

Pendientes: conectar el guard cuando existan AUT-06/AUT-11, acordar cierre de
agencias y comprobar el entorno/organización de la cuenta esperada con
`org-contador`. No se hizo push ni se abrió PR.
