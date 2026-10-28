---
number: 5
title: "T-01 | Validar tarjeta y PIN en ATM"
type: task
code: T-01
parent: "[[E3 Transacciones ATM]]"
status: Backlog
priority: P1
size: M
estimate: 3
estimate_be: 2
estimate_fe: 1
etapa: "3"
start_date: 2026-11-04
target_date: 2026-11-09
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/5
---

> Como **cliente**, quiero **validar mi tarjeta y PIN en el ATM** para **abrir una sesión segura y operar**.

**Etapa:** 3 · **QA:** 0 d · **Tablas:** `ATM.ATM`, `Tarjeta.Tarjeta`, `Tarjeta.TarjetaHis`, `Canal.Canal` · `TarjetaPIN` (SeguridadDB)

## Criterios de aceptación

- [ ] Tarjeta activa + PIN correcto abren una sesión ATM de 5 minutos (ATM-01)
- [ ] PIN incorrecto suma un intento; al llegar a N la tarjeta se bloquea
- [ ] Terminal inactivo, tarjeta no activa o bloqueada se rechazan con su código ISO
- [ ] La sesión se cierra con ATM-09 o al vencer
- [ ] PAN y PIN nunca aparecen en logs, URLs ni evidencias
- [ ] Pruebas: acceso válido, PIN incorrecto, bloqueo por intentos, tarjeta bloqueada, terminal fuera de servicio

## Dependencias

- Requiere: A-05, F-08 (G-02)
- Bloquea: T-02, T-03, T-05, T-06, T-07

## Pendiente

- G-02 (aplicar): hash, salt e intentos del PIN. Definir N, ventana de conteo y desbloqueo.
