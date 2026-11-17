# E4-01 Motor contable

`generar_asiento(conn, OperacionContable(...))` usa la transacción del llamador.
Pase una clave estable del evento, agencia, identidad interna, fecha contable,
importes Decimal y, para una transacción, su ID. Use el mismo contexto al
reintentar. El motor rechaza una clave reutilizada con otra huella.

Las plantillas AC-01 conservan sus IDs y detalles. La vigencia se elige con el
día contable y solo se consideran versiones activadas. Los roles se pasan como
un mapa interno de (origen, código de rol) a ID de cuenta, resuelto por el
módulo invocador desde su configuración. La comisión usa (COMISION, None).
Cada base indicada en las líneas debe aparecer en importes, aun con valor cero.
El motor omite los ceros, valida los auxiliares de ocho dígitos, cuadra,
numera con el procedimiento SQL nativo, contabiliza y actualiza saldo del
auxiliar y de sus ascendientes. Ante un error el llamador debe hacer rollback.

`reversar(conn, id_asiento, motivo, actor=...)` genera el espejo y conserva
las líneas originales. En un asiento asociado a una transacción, el adaptador
de la operación debe pasar el ID de la transacción original y del reverso como
parte de esa misma transacción. Se usa la fecha contable vigente de Ecuador.

## Matriz y consumidores

| Familia | Débito | Crédito | Consumidor |
|---|---|---|---|
| DOT_CAJA | 11010510 | 11010505 | CAJ-07 |
| DEV_CAJA | 11010505 | 11010510 | CAJ-15 |
| DOT_ATM | 11010515 | 11010505 | Disponible para el flujo de custodia ATM |
| CAJA_DEPOSITO | 11010510 | CAPITAL del producto | Disponible para el adaptador de ventanilla |

La matriz del depósito incluye la comisión definida en #380: débito CAPITAL
y crédito a la cuenta de ingreso de la comisión. Una comisión cero omite esas
dos líneas y no requiere resolver la cuenta de comisión. Consulte el día
contable en la misma conexión del módulo. CAJ-07 usa el ID de la dotación,
CAJ-15 el ID de la devolución, con los prefijos DOTACION_CAJA y DEVOLUCION_CAJA.
La integración conserva la autorización y el movimiento de efectivo existentes.

Para un consumidor nuevo, dentro de la transacción del movimiento:

```python
from decimal import Decimal
from app.modules.contabilidad.asientos import OperacionContable, generar_asiento

id_asiento = generar_asiento(conn, OperacionContable(
    codigo_plantilla="CAJA_DEPOSITO",
    clave_evento=f"TRANSACCION:{id_transaccion}",
    id_agencia=id_agencia,
    id_fecha_contable=id_fecha_contable,
    id_usuario=actor,
    fecha_hora=fecha_hora,
    importes={"PRINCIPAL": Decimal("100.00"), "COMISION": Decimal("0.00")},
    id_transaccion=id_transaccion,
    cuentas_por_rol={("PRODUCTO", "CAPITAL"): id_auxiliar_capital},
))
```

Obtenga el auxiliar del subproducto desde una configuración validada. El
llamador suministra los IDs de las cuentas resueltas. Propague las excepciones
hasta el bloque transaccional. Una plantilla ausente devuelve
PLANTILLA_NO_DEFINIDA. Un segundo reverso devuelve ASIENTO_YA_REVERSADO.

## Orden de instalación propuesto para Azure

1. Ensayar el corte E2-01 y conciliar el saldo antes y después sobre una copia
   restaurada. Aplicar 001 y 004 y ejecutar el corte autorizado durante la
   ventana de mantenimiento, con evidencia y dos identidades verificadas.
   Ejecutar 005_auxiliar_faltantes tras verificar los usos de 199025.
2. Aplicar en orden 20261111_ac01_01, 20261111_ac01_02,
   20261117_e401_versiones y 20261117_e401_versiones_semilla. Revisar preexistencias
   AC-01 antes de la instalación. La semilla falla si una familia inicial
   difiere y preserva las versiones previas.
3. Confirmar las cuatro plantillas, cuentas imputables activas y saldos del
   corte antes de desplegar la aplicación con CAJ-07 y CAJ-15. Las rutas
   requieren la semilla y revierten el movimiento si la contabilización falla.
4. Ejecutar los ensayos SQL locales y las pruebas de cada ruta. El ensayo de
   este repositorio usa una proyección del esquema, con catálogos mínimos de
   conceptos y tipos. La aprobación de los cambios en Azure queda a cargo del DBA.

## Dependencias de otros módulos

F-08 clasifica G-11 como descartada como brecha de migración. El proveedor de
ventanilla en develop sigue sin emitir los identificadores requeridos por
su contrato: NumeroComprobante, Secuencial, CodigoProcesamiento y, cuando
correspondan al canal, STAN, RRN y autorización. Los valores de consulta de
saldo ATM vienen del protocolo ATM y no especifican el contrato de caja.
Transacciones debe designar el generador y confirmar canal, país, tipos de
movimiento y registro y reverso de comisiones. Una vez resueltos esos
contratos, puede consumir CAJA_DEPOSITO usando el ejemplo anterior.