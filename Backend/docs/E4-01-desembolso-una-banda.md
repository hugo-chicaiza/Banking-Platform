# CREDITO_DESEMBOLSO_CUENTA — versión aprobada de una banda

El [manifiesto E4-03 para Azure Dev](../scripts/sql/manifiestos_e403/credito_desembolso_cuenta_dev.json) reutiliza el tipo automático activo `CREDITO_DESEMBOLSO` (14) y el concepto activo `DESEMBOLSO_CREDITO` (7). La versión v1, ID 36, quedó activa y aprobada independientemente el 27/11/2026 a las 05:43:32.0616002 según SQL. La creó el usuario 37 y la aprobó el 38. El selector de E4-01 devuelve el ID 36 para la fecha contable 30/11/2026, inicio de su vigencia.

## Mapeos verificados en Dev

| Origen | Resolución del caso |
| --- | --- |
| PRODUCTO / CARTERA | Consumo `140205` y microcrédito `140405` para `POR_VENCER / ORIGINAL / tramo 1` (1 a 30 días). |
| CONTRAPRODUCTO / CAPITAL | Para el ejemplo, ahorro AHO001 resuelve `21013505` con el mapeo a nivel de producto. El productor debe resolver la cuenta del subproducto destino y respetar sus asignaciones específicas. |
| FIJA | SOLCA `25059005`, ID Dev 1217. Coincide con `Credito.Impuesto.IdCuentaContable` para SOLCA. Es una hoja acreedora, activa e imputable bajo `250590`. |

## Simulación E4-03

Para el ejemplo de #31, el valor de la base `PRINCIPAL` en **esta familia** es el **neto** acreditado, y `IMPUESTO` es SOLCA. El bruto es la suma de ambos. El productor debe comprobar esta identidad contra el capital contractual antes de invocar el motor.

| Base | Debe consumo | Debe microcrédito | Haber | Importe |
| --- | --- | --- | --- | ---: |
| PRINCIPAL | 140205 | 140405 | 21013505 | 2.487,50 |
| IMPUESTO | 140205 | 140405 | 25059005 | 12,50 |
| **Total por caso** | | | | **2.500,00 por lado** |

La prueba valida el JSON con el cargador oficial y el modelo del editor. Ejecuta el simulador E4-03 contra una proyección SQL Server local, resuelve los IDs locales por código y verifica las cuatro líneas y los totales por separado. La preparación mínima del catálogo de prueba se revierte en cada caso. El manifiesto conserva el ID fijo de SOLCA de Azure Dev.

```powershell
# Desde Backend, en una copia descartable creada con el laboratorio E2-01.
$env:E401_DESEMBOLSO_SQL_LAB = 'CooperativaDB_E201_Lab_<sufijo>'
python -m pytest -q tests/integration/test_e401_desembolso_una_banda.py
```

## Antes de habilitar al productor

- Usar esta versión únicamente para una banda. Antes de invocar el motor, rechazar repartos con más de una banda positiva. Probar que ese rechazo no persiste movimientos ni asientos.
- Crédito debe entregar el reparto por bandas y acordar la representación multibanda. El contrato actual del motor admite una cuenta por `(origen, rol)`.
- Crédito y Transacciones deben integrar la creación de crédito y cuotas, el abono, la retención SOLCA, la clave idempotente, el asiento y el reverso autorizado. La garantía E6-05, si aplica, es un hecho vinculado y conserva su propia regla.
- Mantener la cobertura integral de desembolso pendiente hasta probar el productor real. Las simulaciones verifican la regla contable de una banda.

Fuentes. [E9-08 #31](https://github.com/hugo-chicaiza/Banking-Platform/issues/31) · [E3-05 #378](https://github.com/hugo-chicaiza/Banking-Platform/issues/378) · [CUC segmento 1](../scripts/sql/e201/cuc_segmento_1.csv)
