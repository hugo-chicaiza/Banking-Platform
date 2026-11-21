# E0 · Configuración en Azure

Pasos en el portal de Azure para que funcione lo desarrollado en los E0.
**Obligatorio** = sin ese paso la función no corre o no avisa. **Opcional** = mejora; se puede dejar para después.

App Service: `backend-dev` (desde `develop`) y el principal (desde `main`).
Servidor SQL: `enquohub`. Identidad: `backend-dev-id-bf29`.

## Resumen

| # | Paso | E0 | ¿Obligatorio? |
|---|---|---|---|
| 1 | Rol «Colaborador de SQL Server» para `backend-dev-id-bf29` | E0-02 | Sí |
| 2 | Credencial federada del entorno `respaldos` | E0-02 | Sí |
| 3 | «Always On» activado en el App Service | E0-06 | Sí |
| 4 | Registros del App Service hacia Log Analytics | E0-05, E0-06, E0-13 | Sí (para las alertas) |
| 5 | Alertas `AUD_RELEVO_ALERTA` y `TAREA_SIN_EJECUTAR` | E0-05, E0-06 | Sí |
| 6 | Comprobar los web jobs tras el despliegue | E0-06 | Sí |
| 7 | Variables del App Service | — | **Ninguna nueva obligatoria** |
| 8 | Variables opcionales | E0-05, E0-13 | No |
| 9 | Variables que **no** se deben poner | E0-01 | — |
| 10 | Login SQL de la app con menos privilegios | Transversal | Recomendado |

---

## 1. Rol en el servidor SQL (E0-02) · Obligatorio
Lo necesita el respaldo para abrir y cerrar la regla de firewall temporal del runner de GitHub.

1. **SQL servers → `enquohub` → Control de acceso (IAM) → Agregar → Agregar asignación de roles.**
2. Rol: **Colaborador de SQL Server**.
3. Asignar acceso a: **Identidad administrada** → `backend-dev-id-bf29`.
4. **Revisar y asignar.** La captura que compartieron se quedó en el paso «Miembros».
5. Comprobar en **Asignaciones de roles** que aparece.

## 2. Credencial federada (E0-02) · Obligatorio
Permite que el workflow de respaldo inicie sesión en Azure sin contraseña (OIDC). La credencial que ya existe es la
del despliegue y no sirve para el entorno `respaldos`.

Antes, comprobar que `backend-dev-id-bf29` es la identidad correcta. Los workflows de respaldo usan el mismo
secreto de GitHub que el despliegue (`AZUREAPPSERVICE_CLIENTID_5769…`). En **Credenciales federadas** de la
identidad correcta ya debe existir una credencial para `Banking-Platform` (la del despliegue de `develop`). Si está
en otra de las tres identidades (`a699`, `bac1`), hacer los pasos 1 y 2 en esa.

1. **Identidades administradas → `backend-dev-id-bf29` → Credenciales federadas → Agregar credencial.**
2. Escenario: **GitHub Actions que implementan recursos de Azure**.
3. Organización: `hugo-chicaiza` · Repositorio: `Banking-Platform`.
4. Tipo de entidad: **Environment** · Nombre: `respaldos`.
5. Nombre de la credencial: `github-respaldos` · **Agregar**.

Después, en GitHub:
- Pasar `respaldo-bd.yml` y `restaurar-bd.yml` a `main`: GitHub solo programa y lanza a mano los workflows de la
  rama por defecto.
- Lanzar `respaldo-bd.yml` a mano, confirmar el archivo en B2 y probar `restaurar-bd.yml`. Anotar el resultado en
  [E0-02-respaldos.md](E0-02-respaldos.md).

## 3. «Always On» (E0-06) · Obligatorio
Los web jobs programados (`atm06-recovery` cada minuto, `sis-vigilante` cada 5 minutos) **solo corren con Always On**.
Sin él, Azure descarga la aplicación cuando no tiene tráfico y las tareas dejan de ejecutarse.

1. **App Service → Configuración → Configuración general → Always On: Activado → Guardar.**
2. Hacerlo en `backend-dev` y en el principal. Requiere un plan Basic o superior; en el plan gratuito no existe.

## 4. Registros hacia Log Analytics · Obligatorio para las alertas
1. Crear un **área de trabajo de Log Analytics**, o usar una existente, en la misma región.
2. **App Service → Supervisión → Configuración de diagnóstico → Agregar.**
   - Marcar **AppServiceConsoleLogs** y **AppServiceAppLogs**.
   - Destino: el área de trabajo de Log Analytics.
3. **App Service → Supervisión → Registros de App Service**: *Application logging (Filesystem)* activado, nivel
   **Information**. Sirve para el *Log stream*.
4. Retención recomendada: 30 días (E0-13).

## 5. Alertas (E0-05, E0-06) · Obligatorio
El backend escribe estas líneas con nivel ERROR y un código fijo. La alerta es lo que avisa al equipo.

**Monitor → Alertas → Crear → Regla de alertas** · Recurso: el área de trabajo de Log Analytics · Señal: *Búsqueda
de registros personalizada*.

| Alerta | Consulta | Evaluación | Qué significa |
|---|---|---|---|
| Relevo de auditoría atrasado | `AppServiceConsoleLogs \| where ResultDescription has "AUD_RELEVO_ALERTA"` | cada 5 min, umbral > 0 | Un evento lleva más de 10 minutos sin llegar a la bitácora |
| Tarea programada sin ejecutar | `AppServiceConsoleLogs \| where ResultDescription has "TAREA_SIN_EJECUTAR"` | cada 5 min, umbral > 0 | Una tarea no corrió dentro de su ventana |

Grupo de acciones: correo a los responsables (Matthew, Eli). La misma alerta queda también como evento en la
bitácora (`AUD_RELEVO_ALERTA`, `SIS_TAREA_SIN_EJECUTAR`).

## 6. Comprobar los web jobs tras el despliegue (E0-06) · Obligatorio
1. **App Service → Configuración → WebJobs**: deben aparecer `atm06-recovery` y `sis-vigilante`, tipo
   *Triggered*, con su programación.
2. En la base, `Sistema.TareaEjecucion` debe tener filas nuevas de `ATM06_RECUPERACION` (cada minuto) y
   `SIS_VIGILANTE` (cada 5 minutos).
3. Si un web job falla, su registro está en **WebJobs → Logs**.

## 7. Variables del App Service · ninguna nueva obligatoria
Los E0 no agregaron variables obligatorias: todas tienen un valor por defecto seguro. Las que el App Service ya
tiene (conexión a la base, WorkOS, `COOPERATIVA_NOMBRE`, `ATM_PIN_RECOVERY_ENABLED`, etc.) siguen igual.

## 8. Variables opcionales
**App Service → Configuración → Variables de entorno → Configuración de la aplicación.**

| Variable | Valor por defecto | Cuándo ponerla | E0 |
|---|---|---|---|
| `LOG_FORMATO` | `texto` | `json` si van a consultar los registros por campos en Log Analytics | E0-13 |
| `AUD_RELEVO_ALERTA_MINUTOS` | `10` | Solo si se quiere otro límite para la alerta del relevo | E0-05 |
| `LOG_LEVEL` | `INFO` | `WARNING` para menos volumen | E0-13 |

## 9. Variables que **no** se deben poner en el App Service
| Variable | Por qué |
|---|---|
| `MIGRACIONES_HABILITADAS`, `MIGRACIONES_ODBC_COOPERATIVA`, `MIGRACIONES_ODBC_SEGURIDAD` | Son del login administrativo de migraciones (E0-01). Las usa solo quien ejecuta migraciones, nunca la app |
| `BACKUP_PASSPHRASE`, `B2_*`, `SQL_ADMIN_*` | Son de los workflows de respaldo. Viven en los secretos de GitHub y en `.env.secretos` local |

## 10. Login SQL de la aplicación · Recomendado
Hoy la app se conecta con `devcat`, que es **administrador del servidor** y `db_owner` de las dos bases. Si alguien
compromete la app, tiene control total de la base. Recomendado:
1. Crear un login propio de la app con `db_datareader`, `db_datawriter` y `EXECUTE` sobre los procedimientos que
   usa, en las dos bases.
2. Cambiar la cadena de conexión del App Service a ese login.
3. Dejar `devcat` solo para migraciones y emergencias, y cambiar su contraseña (se compartió en el chat).

## Secretos compartidos en el chat · Rotar
- **Backblaze B2**: crear una llave nueva limitada al bucket, actualizar `B2_KEY_ID` y `B2_APP_KEY` en GitHub y
  borrar la anterior.
- **Frase de cifrado**: si se cambia, guardar la anterior en `.env.secretos` con su fecha. Los respaldos de los
  últimos 14 días siguen cifrados con ella.
