# E0-02 · Respaldos, restauración y ensayo de migraciones

| Pieza | Estado | Workflow |
|---|---|---|
| Respaldo diario cifrado | **Activo** (desde que el workflow esté en `main`, la rama por defecto: GitHub solo programa desde ahí) | `.github/workflows/respaldo-bd.yml` |
| Restauración | **Activa**, manual | `.github/workflows/restaurar-bd.yml` |
| Ensayo de migraciones en una copia | **Apagado** (`ENSAYO_MIGRACIONES` ≠ `true`) | `.github/workflows/ensayo-migraciones.yml` |

## Respaldo

1. 02:00 (Ecuador) cada día, o a mano (*Actions → Respaldo de bases de datos → Run workflow*).
2. Abre una regla temporal en el firewall de `enquohub` solo para la IP del runner (se borra al final aunque falle).
3. Exporta CooperativaDB y SeguridadDB (BACPAC) con el login **`AdminRespaldos`** (solo lectura de datos y
   definiciones; `dbmanager` en master para poder restaurar a una base nueva; no es dueño de ninguna base).
4. Comprime (gzip) y **cifra** con AES-256 (`openssl enc -aes-256-cbc -pbkdf2 -iter 600000`, frase `BACKUP_PASSPHRASE`).
5. Sube el archivo y su SHA-256 a **Backblaze B2** (`enquo-respaldos-coop`, privado, cifrado del lado del servidor),
   en `<Base>/<Base>_<AAAAMMDDTHHMMSSZ>.bacpac.gz.enc`. El bucket oculta cada respaldo a los **14 días** y lo borra al día
   siguiente (regla de ciclo de vida).

## Restauración

*Actions → Restaurar respaldo de base de datos → Run workflow*:

- `modo=verificar` (por defecto): descarga, comprueba la suma, descifra y restaura en un **SQL Server temporal dentro del
  runner**; el resumen del trabajo muestra el respaldo usado, el tiempo y las filas por tabla. No toca Azure y la copia
  desaparece con el runner (no queda una copia con datos reales fuera de la cuenta, PCI E-236).
- `modo=azure`: restaura en una **base nueva** de `enquohub` (nombre en `destino`, escribir `RESTAURAR` en `confirmar`).
  Nunca encima de `CooperativaDB` ni `SeguridadDB`, y no sobrescribe una base que ya existe. Se crea en el nivel Basic:
  **tiene costo; bórrela al terminar**.

### Restauración de la base compartida tras un desastre

1. `modo=azure` con `destino=CooperativaDB_restaurada_<fecha>` (y lo mismo para SeguridadDB).
2. Verificar la copia (conteos, últimos movimientos).
3. Con la aprobación de `hugo-chicaiza`: renombrar la base dañada y la restaurada en el portal de Azure
   (o apuntar `COOPERATIVA_DB_NAME`/`SEGURIDAD_DB_NAME` del App Service a la restaurada) y reiniciar el backend.
4. Registrar fecha, respaldo usado y tiempo empleado en el issue del incidente.

**Prueba única del procedimiento (criterio 4):** se registra aquí con fecha, respaldo y tiempo después de la primera
ejecución de `modo=verificar`.

| Fecha | Respaldo | Modo | Tiempo | Resultado |
|---|---|---|---|---|
| | | | | |

## Ensayo de migraciones (apagado)

Con `ENSAYO_MIGRACIONES=true`, cada pull request que toca `Backend/migrations/` restaura el último respaldo en un SQL
Server temporal, aplica las migraciones con el ejecutor de E0-01 y verifica que ninguna tabla pierda filas. Si falla, el
pull request queda en rojo.

## Configuración

| Dónde | Nombre | Para qué |
|---|---|---|
| Secretos de GitHub | `B2_KEY_ID`, `B2_APP_KEY`, `B2_BUCKET`, `B2_ENDPOINT` | Backblaze B2 (llave limitada al bucket) |
| | `BACKUP_PASSPHRASE` | Cifrado de los respaldos. **Guardar también fuera de GitHub**: sin ella no se restaura |
| | `SQL_ADMIN_USER`, `SQL_ADMIN_PASSWORD` | Login `AdminRespaldos` |
| | `AZUREAPPSERVICE_*` (ya existían) | OIDC con Azure para la regla temporal del firewall |
| Entorno de GitHub | `respaldos` | Los tres workflows corren en él |
| Azure (una vez) | Credencial federada `repo:hugo-chicaiza/Banking-Platform:environment:respaldos` en la identidad de despliegue; rol **SQL Server Contributor** sobre `enquohub` | Iniciar sesión y abrir/cerrar la regla del firewall |
| Variable de GitHub | `ENSAYO_MIGRACIONES` | `true` activa el ensayo |
