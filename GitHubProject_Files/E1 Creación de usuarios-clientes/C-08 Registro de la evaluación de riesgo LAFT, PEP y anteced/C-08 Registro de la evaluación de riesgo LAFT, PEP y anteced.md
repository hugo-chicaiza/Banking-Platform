---
number: 58
title: "C-08 | Evaluación de riesgo LAFT, PEP y antecedentes"
type: task
code: C-08
parent: "[[E1 Creación de usuarios-clientes]]"
status: Backlog
priority: P2
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
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/58
---

> Como **asesor u oficial de cumplimiento**, quiero **registrar la evaluación de riesgo LAFT, PEP y antecedentes del cliente** para **habilitarlo o bloquearlo antes de darle productos**.

**Etapa:** 3 · **QA:** 0 d · **Tablas:** `Clientes.RiesgoCliente`, `Catalogo.TipoAntecedente`, `Clientes.Cliente`

## Criterios de aceptación

- [ ] Se registra nivel LAFT (Bajo/Medio/Alto), PEP, antecedentes con su tipo, resultado y observaciones (CLI-13)
- [ ] La última evaluación queda vigente y cambia el estado del cliente (ver reglas)
- [ ] Se consulta el historial de evaluaciones (CLI-14)
- [ ] Un cliente Rechazado o con antecedente que impide vinculación no abre cuentas ni pide créditos
- [ ] Pruebas: Aprobado (Pendiente → Activo), Observado, Rechazado (→ Bloqueado), antecedente sin tipo, historial

## Reglas de negocio

- `trg_RiesgoCliente_Evaluacion`: Rechazado → `Bloqueado`; Aprobado desde `Pendiente` → `Activo`; Observado → sin cambio.
- Antecedentes exigen tipo y viceversa (`CK_RiesgoCliente_Antecedente`).

## Dependencias

- Requiere: C-01, F-09 (CAT-04)
- Bloquea: A-01, CR-01
