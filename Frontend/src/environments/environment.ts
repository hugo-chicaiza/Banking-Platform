import type { AppEnvironment } from './environment.model';

/**
 * Entorno de DESARROLLO (valor por defecto del árbol de código).
 *
 * `angular.json` sustituye este archivo por `environment.staging.ts` o
 * `environment.production.ts` mediante `fileReplacements`. No importar los
 * otros archivos directamente: romperían la sustitución.
 */
export const environment: AppEnvironment = {
  name: 'development',
  // Ruta relativa: `proxy.conf.json` la reenvía al backend local.
  apiBaseUrl: '/api/v1',
  production: false,
  enableDebugLogs: true,
  sessionIdleTimeoutMinutes: 60,
};
