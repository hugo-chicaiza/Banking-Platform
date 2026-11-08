---
number: 146
title: "ATM-06 | POST /api/v1/atm/cambio-pin"
type: api
code: ATM-06
parent: "[[T-06 Cambiar PIN]]"
status: Backlog
priority: P2
size: 
estimate: 
estimate_be: 
estimate_fe: 
etapa: "3"
start_date: 2026-11-04
target_date: 2026-11-09
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/146
---

`POST /api/v1/atm/cambio-pin` · **Roles:** ATM (sesión, también la restringida) · **Historia:** T-06 (#11) · **OpenAPI:** `ATM06`

Cambio de PIN en el cajero. Es también el paso que **activa una tarjeta de débito nueva**: el primer cambio del PIN temporal la pasa de `Generada` a `Activa` (A-05).

| Lee | Escribe | DB / Componente |
|---|---|---|
| `Tarjeta.Tarjeta`, `SeguridadDB.Tarjetas.TarjetaPIN`, repositorio aislado de PAN ficticios | `Tarjeta.Tarjeta`, `Tarjeta.TarjetaHis`, `SeguridadDB.Tarjetas.TarjetaPIN`, revocación de sesión ATM | `CooperativaDB`, `SeguridadDB`, HSM |

## Reglas de negocio

1. Requiere sesión ATM con `require_sesion_atm` (no `require_sesion_operativa`): acepta la sesión restringida de ATM-01 (`cambioPinRequerido = true`).
2. Los PIN llegan como **PIN Block ISO 9564-1 formato 4 (AES-256)**, nunca en claro. El body se lee a mano, como en ATM-01, para que un error de validación no devuelva su contenido.
3. Exige el PIN actual: se verifica con `hsm.verificar_pin` contra el `PINOffset` de `TarjetaPIN` → si no coincide, `401 PIN_INCORRECTO` y suma un intento (mismas funciones que ATM-01: `guardar_resultado_pin`; al tercero, `423 PIN_BLOQUEADO` y bloqueo de la tarjeta si está `Activa`).
4. PIN nuevo de 4 dígitos y no trivial → `422 PIN_DEBIL`. El Offset nuevo se calcula con `hsm.generar_offset(pinBlockNuevo, keyReference, pan)`, que ya rechaza los PIN triviales.
5. El PIN nuevo debe ser distinto del actual → `422 PIN_DEBIL`. Con el mismo PAN y la misma PVK, el mismo PIN da el mismo Offset: basta comparar el Offset nuevo con el guardado.
6. **Activación de débito:** si la tarjeta es de débito, está `Generada` y el PIN era temporal (`RequiereCambio = 1`), pasa a `Activa` con `TarjetaHis` (`Activacion`, “Activación por primer cambio de PIN”, canal ATM).
7. Se guarda el Offset nuevo con `RequiereCambio = 0`, `IntentosFallidos = 0` y `FechaUltimoCambio`; se registra `TarjetaHis` (`CambioPin`, `Descripcion = 'Cambio de PIN en ATM'`, que TAR-06 muestra como `origen: Cliente`) sin el PIN.
8. Orden de escritura: primero la activación en `CooperativaDB` y luego el Offset en `SeguridadDB`. Si falla `SeguridadDB`, la tarjeta queda activa con el PIN temporal: el siguiente ATM-01 vuelve a abrir la sesión restringida y el cambio se puede repetir.
9. Si la sesión era restringida, se revoca después del cambio (`revocar_sesion_atm`): el cliente vuelve a autenticarse con el PIN nuevo (ATM-01) para operar.
10. Nunca registrar PAN, PIN, PIN Blocks, PIN Offset ni el token en logs, URLs ni errores.

## Flujo

1. Validar la sesión ATM (restringida o normal) y que no esté revocada.
2. Obtener el PAN ficticio y verificar el PIN actual con el HSM; actualizar intentos.
3. Calcular el Offset del PIN nuevo y validar fortaleza y diferencia con el actual.
4. Si corresponde, activar la tarjeta de débito (`Generada → Activa`) con su historial.
5. Guardar el Offset nuevo con `RequiereCambio = 0` y registrar `CambioPin`.
6. Revocar la sesión si era restringida y responder 204.

## Request

Body `AtmCambioPinRequest`:

| Campo | Tipo | Req. | Regla |
|---|---|---|---|
| encryptedPinBlockActual | string(32) | Sí | PIN Block ISO-4 del PIN actual, hex |
| encryptedPinBlockNuevo | string(32) | Sí | PIN Block ISO-4 del PIN nuevo, hex |
| keyReference | string | Sí | Referencia de clave AES-256 autorizada por el servidor |

```json
{
  "encryptedPinBlockActual": "00112233445566778899AABBCCDDEEFF",
  "encryptedPinBlockNuevo": "FFEEDDCCBBAA99887766554433221100",
  "keyReference": "TEST-KEY-01"
}
```

*Valores ficticios. Para probar, cada PIN Block se arma con `POST /api/v1/pruebas/pin-block` (PIN pad simulado).*

## Response `204`

Sin contenido.

## Errores

Formato ProblemDetails (ver F-04). Además de 400/401/403:

| HTTP | `code` | Cuándo |
|---|---|---|
| 401 | `SESION_ATM_INVALIDA` | Sin sesión ATM válida o revocada |
| 401 | `PIN_INCORRECTO` | El PIN actual no coincide |
| 423 | `PIN_BLOQUEADO` | Se alcanzó el límite de intentos |
| 422 | `PIN_DEBIL` | PIN nuevo trivial o igual al actual |
| 422 | `PIN_BLOCK_INVALIDO` | PIN Block con formato o estructura inválidos |
| 422 | `CLAVE_NO_AUTORIZADA` | La referencia de clave no está autorizada |
| 503 | `HSM_NO_DISPONIBLE` | No se puede completar el procesamiento criptográfico |

## Prueba pendiente

- [ ] Con ATM-06 terminado, probar la activación de débito de punta a punta: aprobar (TAR-04) → descargar el sobre (TAR-07) → ATM-01 con el PIN temporal (`cambioPinRequerido: true`) → ATM-06 → la tarjeta pasa de `Generada` a `Activa`, TAR-06 muestra `CambioPin` con `origen: Cliente` y el PIN temporal deja de servir.

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
- [ ] Primer cambio de PIN de una tarjeta de débito `Generada`: queda `Activa`, `RequiereCambio = 0` y la sesión restringida revocada
- [ ] Sin PAN, PIN, PIN Blocks, PIN Offset, contraseñas ni tokens en logs

## Pendiente

- Implementar el endpoint (ATM-01 ya emite la sesión restringida y `require_sesion_operativa` existe en `app/modules/atm/session.py`).
