---
number: 139
title: "ATM-01 | POST /api/v1/atm/auth"
type: api
code: ATM-01
parent: "[[T-01 Validar tarjeta y PIN]]"
status: Backlog
priority: P1
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/139
---

`POST /api/v1/atm/auth` · **Roles:** Terminal ATM · **Historia:** T-01 (#5) · **OpenAPI:** `ATM01`

Autentica tarjeta y PIN en un terminal y abre sesión.

| Lee | Escribe | DB |
|---|---|---|
| `ATM.ATM`, `Tarjeta.Tarjeta`, `Canal.Canal`, `Cuentas.Cuenta` | `Tarjeta.TarjetaHis`, `Transacciones.Transaccion` | — |

## Reglas de negocio

1. El terminal debe existir y estar activo → si no, `409 ATM_FUERA_DE_SERVICIO`.
2. La tarjeta se busca por hash del PAN y debe estar `Activa` → `409 TARJETA_NO_ACTIVA` (ISO 54/62); `Bloqueada` → `423 TARJETA_BLOQUEADA` (ISO 75).
3. PIN incorrecto → `401 PIN_INCORRECTO` (ISO 55) y suma un intento; al llegar a N la tarjeta pasa a `Bloqueada` con `TarjetaHis`.
4. PIN correcto reinicia los intentos y emite un JWT de 5 min con `scope=atm`, tarjeta, terminal y cuentas autorizadas.
5. Nunca registrar PAN, PIN ni token en logs ni URLs.

## Flujo

1. Validar terminal y canal (`RequiereTarjeta`, `RequierePin`).
2. Validar tarjeta y PIN; actualizar intentos o bloquear.
3. Emitir la sesión ATM y devolver titular y cuentas enmascaradas.

## Request

Body `AtmAuthRequest`:

| Campo | Tipo | Req. | Regla |
|---|---|---|---|
| codigoATM | string(8) | Sí |  |
| numeroTarjeta | string(19) | Sí | PAN; el backend calcula hash y nunca lo registra en logs |
| pin | string(4) | Sí |  |

```json
{
  "codigoATM": "ATM00001",
  "numeroTarjeta": "numeroTarjeta",
  "pin": "pin"
}
```

## Response `200`

`AtmAuthResponse`

```json
{
  "sessionToken": "TOKEN_ATM_FICTICIO",
  "expiresIn": 300,
  "titular": "Cliente de ejemplo",
  "cuentas": [
    {
      "idCuenta": 501,
      "numeroCuentaEnmascarado": "********0501",
      "tipoCuenta": "Ahorros"
    }
  ]
}
```

## Errores

Formato ProblemDetails (ver F-04). Además de 400/401/403:

| HTTP | `code` | Cuándo |
|---|---|---|
| 401 | `PIN_INCORRECTO` | El PIN no coincide (código 55) |
| 423 | `TARJETA_BLOQUEADA` | La tarjeta está bloqueada (código 75) |
| 409 | `TARJETA_NO_ACTIVA` | La tarjeta no está Activa (código 54/62) |
| 409 | `ATM_FUERA_DE_SERVICIO` | El terminal no está activo |

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
- [ ] Sin PAN, PIN, contraseñas ni tokens en logs

## Controles compartidos con TAR-01 y TAR-05

ATM-01 debe usar los mismos algoritmos con que se emitieron la tarjeta y el PIN; si no, nunca coinciden:

- **Búsqueda de la tarjeta:** `Tarjeta.Tarjeta.HashNumeroTarjeta` = SHA-256 en bytes del PAN solo con dígitos (sin espacios ni guiones), igual que TAR-01.
- **PIN:** verificar con Argon2id (`PasswordHasher().verify`) contra `SeguridadDB.Tarjetas.TarjetaPIN.HashPIN`, igual que lo guarda TAR-05. No recalcular el hash para compararlo: la salt es aleatoria.
- **Intentos:** `TarjetaPIN.IntentosFallidos`, actualizado con bloqueo de fila para evitar condiciones de carrera.
- **Datos sensibles:** `numeroTarjeta` y `pin` no deben aparecer en logs, errores ni URLs; igual que TAR-05, un error de validación no debe devolverlos en la respuesta.

## Pendiente

- Valor de N y cómo se autentica el terminal.
