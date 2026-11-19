# E0-06 · Tareas programadas

## Cómo funciona
Cada tarea es un comando del backend:

```bash
python -m app.core.tareas ejecutar <CODIGO>
python -m app.core.tareas ejecutar <CODIGO> --por <usuario> --motivo "<por qué>"   # ejecución manual
```

- **Bloqueo**: una sola instancia a la vez por código (`sp_getapplock`). Si otra la tiene, sale `EN_CURSO` con código 0, sin hacer nada.
- **Registro**: cada ejecución queda en `Sistema.TareaEjecucion` (inicio, fin, `Exitoso`/`Parcial`/`Fallido`, procesados, modificados, código de error, quién y motivo si fue manual). Sin datos personales.
- **Manual**: exige motivo y que la tarea tenga `PermiteManual = 1`.
- **Catálogo**: `Sistema.Tarea` (descripción, programación, `VentanaEsperadaMin`, estado). Desactivar una tarea = `Estado = 'I'`.

## Tareas

| Código | Disparo | Ventana | Qué hace |
|---|---|---|---|
| `APR_RECUPERACION` | ciclo de la app, cada minuto | 10 min | Recupera aprobadas y cancela pendientes sin acceso |
| `APR_AUD_RELEVO` | ciclo de la app, cada minuto | 10 min | Pasa la bandeja de eventos a la bitácora (y alerta `AUD_RELEVO_ALERTA`) |
| `APR_RESUMEN_ANTIGUAS` | ciclo de la app, diaria | 25 h | Resumen diario de solicitudes antiguas |
| `ATM06_RECUPERACION` | web job `atm06-recovery`, cada minuto | 10 min | Recupera cambios de PIN ATM-06 pendientes |
| `SIS_VIGILANTE` | web job `sis-vigilante`, cada 5 minutos | — | Alerta si otra tarea no corrió dentro de su ventana |

## Alerta de tarea atrasada
Si la última ejecución correcta de una tarea es más antigua que su ventana (o nunca corrió), el vigilante escribe `TAREA_SIN_EJECUTAR` en el registro (nivel ERROR) y el evento `SIS_TAREA_SIN_EJECUTAR` en la bitácora, como máximo una vez por tarea y hora.

## Agregar una tarea
1. Función que devuelve `Conteo` en `app/core/tareas/registro.py` (`TAREAS`).
2. Fila en `Sistema.Tarea` por migración (la prueba `test_cada_tarea_tiene_fila_en_la_migracion` lo exige).
3. Web job en `App_Data/jobs/triggered/<nombre>/` (`run.sh` con LF + `settings.job` con `is_singleton`).

## Estado
- Migración `202611191200_tareas_programadas` **aplicada** en SeguridadDB.
- El web job `atm06-recovery` pasa a usar el ejecutor; `sis-vigilante` es nuevo. Ambos se activan con el despliegue.
