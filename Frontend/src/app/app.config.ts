import {
  provideBrowserGlobalErrorListeners,
  provideZonelessChangeDetection,
  type ApplicationConfig,
} from '@angular/core';
import { provideRouter, withInMemoryScrolling } from '@angular/router';
import { routes } from './app.routes';

/**
 * Proveedores raíz de la aplicación.
 *
 * `provideBrowserGlobalErrorListeners` captura errores no manejados y rechazos
 * de promesas para que no se pierdan en silencio (OWASP Top 10:2025 A10 —
 * Mishandling of Exceptional Conditions). El reporte de esos errores hacia el
 * backend se define junto con el formato ProblemDetails en F-04.
 */
export const appConfig: ApplicationConfig = {
  providers: [
    provideBrowserGlobalErrorListeners(),
    provideZonelessChangeDetection(),
    provideRouter(routes, withInMemoryScrolling({ scrollPositionRestoration: 'enabled' })),
  ],
};
