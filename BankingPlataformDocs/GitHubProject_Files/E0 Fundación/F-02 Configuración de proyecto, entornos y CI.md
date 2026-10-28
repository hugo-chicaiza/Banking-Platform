---
number: 16
title: "F-02 | Configuración de proyecto, entornos y CI"
type: task
code: F-02
parent: "[[E0 Fundación]]"
status: Backlog
priority: P1
size: M
estimate: 3
estimate_be: 3
estimate_fe: 
etapa: "1-2"
start_date: 2026-10-19
target_date: 2026-11-04
state: open
labels: []
assignees: []
url: https://github.com/hugo-chicaiza/Banking-Platform/issues/16
---

> Como **equipo**, quiero **configurar el proyecto, los entornos, el CI y la configuración** para **trabajar todos sobre la misma base**.

**Etapa:** 1-2 · **QA:** 0 d · **Tablas:** —

## Criterios de aceptación

- [ ] `backend/` (FastAPI) y `frontend/` (Angular) arrancan en local siguiendo su README
- [ ] Variables en `.env` con `.env.example` versionado; ninguna credencial en el repositorio
- [ ] Entornos de desarrollo y staging definidos (staging lo pide el Avance 1)
- [ ] `backend-ci.yml` y `frontend-ci.yml` compilan, ejecutan linter y pruebas en cada PR a `main`
- [ ] `main` protegida: una rama por historia y PR revisado

## Dependencias

- Requiere: F-01 (modelos del contrato)
- Bloquea: F-06 (el CI ejecuta sus pruebas)
