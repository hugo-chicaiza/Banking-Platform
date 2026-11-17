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

Instalar las migraciones AC-01 01, AC-01 02 y E4-01 en ese orden tras E2-01,
en SQL local. Antes de habilitar los adaptadores, confirmar los orígenes,
conceptos, tipos, roles por subproducto y cuentas de comisión por ambiente.
La proyección SQL del laboratorio no instala configuraciones operativas:
`tests/integration/e401_sql_lab.py` siembra una dotación de ejemplo e invoca
el motor directamente. El stub de caja y transacciones conserva su bloqueo
hasta disponer de numeración G-11, canales, códigos y comisiones confirmados.
Las integraciones de caja, ATM, cuentas, tarjetas, bóvedas y transacciones
deben aún completar y probar su adopción del motor.
