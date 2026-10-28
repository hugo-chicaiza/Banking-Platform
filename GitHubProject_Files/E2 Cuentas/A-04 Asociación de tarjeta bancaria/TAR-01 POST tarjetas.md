---
number: 129
title: "TAR-01 | POST /api/v1/tarjetas"
type: api
code: TAR-01
parent: "[[A-04 Asociación de tarjeta bancaria]]"
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/129
---

`POST /api/v1/tarjetas` · **Roles:** ASESOR, ADMIN · **Historia:** A-04 (#40) · **OpenAPI:** `TAR01`

Emite una tarjeta asociada a una cuenta.

| Lee | Escribe | DB |
|---|---|---|
| `Cuentas.Cuenta`, `ProductosFinancieros.Producto`, `Tarjeta.BIN` | `Tarjeta.Tarjeta`, `Tarjeta.EnviosTarjeta`, `Tarjeta.TarjetaHis` | `Tarjeta.trg_Tarjeta_Reglas` |

## Reglas de negocio

1. La cuenta debe estar `Activa` y ser del cliente → `409 CUENTA_NO_ACTIVA`.
2. El producto debe ser de tipo `Tarjeta` → `422 PRODUCTO_NO_ES_TARJETA`; el BIN debe ser el de su subproducto (DB 52004).
3. El PAN se genera y nunca se guarda: solo `TokenTarjeta`, `NumeroEnmascarado` y `HashNumeroTarjeta` (SHA-256). Nunca se devuelve completo.
4. Extensión exige tarjeta titular → `422 EXTENSION_REQUIERE_TITULAR`.
5. Nace en `Generada` con `PinAsignado = 0`; si `requiereEnvio`, crea `EnviosTarjeta` `PENDIENTE` con dirección.

## Flujo

1. Validar cuenta, producto y BIN.
2. Generar PAN, token, máscara y hash; insertar tarjeta, envío y `TarjetaHis` en una transacción.
3. Responder 201 con la tarjeta enmascarada.

## Request

Body `TarjetaCreate`:

| Campo | Tipo | Req. | Regla |
|---|---|---|---|
| idCuenta | integer | Sí |  |
| idProducto | integer | Sí | Producto tipo Tarjeta |
| tipoTarjeta | Debito \| Credito | Sí |  |
| nombreTarjeta | string(50) | Sí | Nombre impreso |
| esExtension | boolean | No |  |
| idTarjetaTitular | integer | No | Obligatorio si esExtension |
| requiereEnvio | boolean | No |  |
| direccionEnvio | string(250) | No | Obligatorio si requiereEnvio |
| idCiudadEnvio | integer | No |  |

```json
{
  "idCuenta": 501,
  "idProducto": 3,
  "tipoTarjeta": "Debito",
  "nombreTarjeta": "MARIA MENDOZA",
  "esExtension": false,
  "requiereEnvio": false
}
```

## Response `201`

`Tarjeta`

```json
{
  "idTarjeta": 301,
  "tokenTarjeta": "tok_tarjeta_301",
  "numeroEnmascarado": "4540 12** **** 3456",
  "tipoTarjeta": "Debito",
  "nombreTarjeta": "MARIA MENDOZA",
  "idCliente": 125,
  "idCuenta": 501,
  "idProducto": 3,
  "estadoActual": "PENDIENTE_ACTIVACION",
  "pinAsignado": false,
  "fechaEmision": "2026-10-26",
  "fechaExpiracion": "2031-10-26"
}
```

## Errores

Formato ProblemDetails (ver F-04). Además de 400/401/403:

| HTTP | `code` | Cuándo |
|---|---|---|
| 409 | `CUENTA_NO_ACTIVA` | La cuenta no está Activa |
| 422 | `PRODUCTO_NO_ES_TARJETA` | El producto no es de tipo Tarjeta |
| 422 | `EXTENSION_REQUIERE_TITULAR` | Una extensión necesita su tarjeta titular |

## Definición de terminado

- [ ] Coincide con `openapi.yaml` (request, response y errores)
- [ ] Prueba del caso feliz y de cada error de la tabla
- [ ] Sin PAN, PIN, contraseñas ni tokens en logs
