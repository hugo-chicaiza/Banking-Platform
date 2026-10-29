import type { AppEnvironment } from './environment.model';

/**
 * Entorno de PRODUCCIÓN.
 *
 * `enableDebugLogs` debe quedarse en `false`: los logs de consola del
 * navegador son legibles por el usuario y por cualquier extensión instalada,
 * y en esta aplicación circulan saldos, documentos de identidad y datos de
 * tarjeta (OWASP Top 10:2025 A09 — Logging & Alerting Failures).
 */
export const environment: AppEnvironment = {
  name: 'production',
  apiBaseUrl: '/api/v1',
  production: true,
  enableDebugLogs: false,
  sessionIdleTimeoutMinutes: 15,
};
