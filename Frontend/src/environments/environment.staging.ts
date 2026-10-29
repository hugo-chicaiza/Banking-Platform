import type { AppEnvironment } from './environment.model';

/**
 * Entorno de STAGING (lo exige el Avance 1, ver `docs/07-Deployment/Environments.md`).
 *
 * `apiBaseUrl` es relativo a propósito: el frontend y el backend se publican
 * detrás del mismo origen, de modo que no hace falta CORS ni queda el host del
 * backend escrito en el bundle. Si el equipo decide separarlos por dominio,
 * hay que cambiar este valor y abrir CORS en `BP_CORS_ALLOWED_ORIGINS`.
 */
export const environment: AppEnvironment = {
  name: 'staging',
  apiBaseUrl: '/api/v1',
  production: false,
  enableDebugLogs: false,
  sessionIdleTimeoutMinutes: 30,
};
