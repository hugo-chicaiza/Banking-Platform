# Contrato de la API (E0-03) — **sin activar en el pipeline**

Un archivo OpenAPI por módulo (`<modulo>.json`), generado desde el código y confirmado en el repositorio:

```bash
python scripts/contrato.py exportar      # actualiza los archivos desde el código
python scripts/contrato.py comparar      # código vs contrato: sale 1 y nombra cada diferencia
python scripts/contrato.py convenciones  # avisos: Problem Details, Idempotency-Key en dinero, montos como cadena
```

- Cada historia actualiza el contrato de su módulo como **primera tarea**; backend y frontend lo revisan juntos.
- Un campo que se elimina se marca `deprecated` durante una versión antes de quitarlo.
- Cuando se active (E0-11), el pipeline ejecuta `comparar` y una diferencia rompe la construcción. El frontend genera
  sus tipos y su modo simulado desde estos archivos.
