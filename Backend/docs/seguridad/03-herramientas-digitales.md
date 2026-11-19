# 03 · Inventario de herramientas digitales

Toda salida de una herramienta automática (incluida la IA) se trata como **propuesta**: entra al repositorio solo por
pull request, pasa por el pipeline y la revisa una persona del equipo antes de integrarse.

| Herramienta | Uso previsto | Qué produce | Control de su salida |
|---|---|---|---|
| GitHub (repositorios, issues, pull requests) | Código, planificación, revisión | — | Reglas de rama en `develop`/`main` (E0-11) |
| GitHub Actions | CI, despliegue, respaldos | Construcciones, artefactos, SBOM, respaldos | Workflows versionados; acciones fijadas por hash; secretos protegidos |
| Ruff, Pyright, Bandit, pip-audit | Formato, tipos, análisis estático y dependencias del backend | Hallazgos | Fallan el CI |
| ESLint, TypeScript, Vitest, npm audit, Semgrep | Calidad, tipos, pruebas, dependencias y análisis estático del frontend | Hallazgos | Fallan el CI |
| Gitleaks | Secretos en el código | Hallazgos | Falla el CI |
| SonarCloud | Calidad y seguridad del código | Hallazgos y métricas | Revisión en cada pull request |
| OWASP ZAP (`dast-zap-develop.yml`) | Pruebas dinámicas del frontend desplegado | Reporte | Revisión del equipo |
| **Asistentes de IA (Claude Code y similares)** | Redactar código, pruebas, documentación, revisiones y planificación | Cambios propuestos | Solo por pull request; la persona que lo integra revisa el diff completo y el pipeline debe pasar. La IA **no** recibe secretos ni datos reales de clientes; no ejecuta migraciones ni cambios en la base compartida sin aprobación explícita del responsable; sus cambios en servicios externos (WorkOS, Azure) se registran en el pull request o en el issue |
| Kit DevSecOps (`0_DevSecOps/KIT_DevSecOps`) | Evaluación de seguridad asistida (ASVS, PCI SSS/SLC) | Hallazgos con evidencia | Los hallazgos los valida una persona; no son evidencia de cumplimiento por sí solos |
| CISO Assistant | Gestión de controles de proceso (COMF, SEPS, LOPDP) | Estado de controles y evidencias | Mantenido por el responsable de la evidencia |
| WorkOS Dashboard | Identidad, roles y permisos | Configuración | Solo administradores; cambios de permisos según [permisos generales](../SEG-01-10-roles-permisos-pestanas.md) |
| Azure Portal | Base de datos, App Service, firewall | Configuración | Solo `hugo-chicaiza` y administradores de la cuenta |
| Cloudflare | Hospedaje del frontend y proxy | Configuración | Solo administradores de la cuenta |
| Google Drive | Destino de respaldos cifrados (E0-02) | — | Carpeta compartida solo con la cuenta de servicio y el responsable |
