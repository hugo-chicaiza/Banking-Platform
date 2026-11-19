# E0-01 · Migraciones versionadas y ejecutor con bitácora

**Estado: código listo y APAGADO.** Nada se ejecuta contra la base compartida hasta que el responsable
(`hugo-chicaiza`) lo active. F-08 (#108) no se aplica en este cambio.

## Piezas

| Pieza | Dónde |
|---|---|
| Ejecutor (`estado`, `aplicar`) | `app/core/migraciones/` · `python -m app.core.migraciones <accion> --base cooperativa|seguridad` |
| Carpetas | `migrations/cooperativa/` y `migrations/seguridad/`: `AAAAMMDDHHMM_<modulo>_<descripcion>.up.sql` y su `.down.sql` |
| Migración cero | `000000000000_linea_base.up.sql` en cada carpeta, generada con `scripts/generar_linea_base.py` |
| Bitácora | `Migracion.Bitacora` en cada base: archivo, SHA-256, fecha UTC, quién (`ORIGINAL_LOGIN()`), duración, línea base |

Los `.tsql` sueltos de `migrations/` son los cambios que se aplicaron a mano antes de E0-01: quedan dentro de la
migración cero y no se vuelven a ejecutar. Todo cambio nuevo va en la carpeta de su base.

## Reglas que el ejecutor hace cumplir

1. Solo con el **login administrativo** (`MIGRACIONES_ODBC_<BASE>`): con el login de la aplicación se niega.
2. `aplicar` exige `MIGRACIONES_HABILITADAS=true`; `estado` solo lee.
3. Verifica que la conexión apunte a la base esperada y fija `SESSION_CONTEXT('migration_database')`, que las
   migraciones exigen antes de tocar nada.
4. Si una migración aplicada cambió (SHA-256 distinta), se detiene **antes de aplicar nada** y la nombra.
5. Cada archivo y su registro van en una transacción: si falla, se revierte y no queda registrado.
6. Repetir sin archivos nuevos no cambia nada.
7. Un archivo `.sql` mal nombrado o con sello de fecha repetido detiene todo.

## Activación (cuando el responsable lo decida)

1. Secretos (App Service no los necesita; solo quien ejecuta):
   - `MIGRACIONES_ODBC_COOPERATIVA`, `MIGRACIONES_ODBC_SEGURIDAD`: cadena ODBC completa del login administrativo.
2. Generar la migración cero de cada base y revisarla:
   ```bash
   python scripts/generar_linea_base.py --base cooperativa > migrations/cooperativa/000000000000_linea_base.up.sql
   python scripts/generar_linea_base.py --base seguridad   > migrations/seguridad/000000000000_linea_base.up.sql
   # semillas de referencia (MERGE repetible por clave primaria):
   python scripts/generar_linea_base.py --base cooperativa --semillas Catalogo.Paises,Catalogo.Ciudad >> ...
   ```
   Comprobar en un servidor vacío que la estructura resultante coincide con la compartida (criterio 1, QA).
3. En la base compartida, **registrar** la línea base sin ejecutarla y aplicar el resto:
   ```bash
   MIGRACIONES_HABILITADAS=true python -m app.core.migraciones estado  --base cooperativa
   MIGRACIONES_HABILITADAS=true python -m app.core.migraciones aplicar --base cooperativa --marcar-linea-base
   ```
4. Antes de la ejecución real, el ensayo en una copia restaurada y el respaldo previo son E0-02.

Una migración ejecutada en producción **no se edita**: la corrección es una migración nueva. Los `.down.sql` se
ejecutan a mano y solo fuera de producción.
