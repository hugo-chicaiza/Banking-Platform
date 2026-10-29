/**
 * Contrato de configuración del frontend.
 *
 * Reglas (F-02):
 * 1. Aquí solo van valores NO sensibles. Todo lo que se compila en el bundle
 *    es público: cualquier usuario puede leerlo con las herramientas del
 *    navegador. Claves de API, secretos de cliente y cadenas de conexión
 *    nunca entran en este archivo ni en ningún otro del frontend.
 * 2. Añadir un campo obliga a actualizar las tres implementaciones
 *    (`environment.ts`, `environment.staging.ts`, `environment.production.ts`);
 *    el `readonly` y el tipado hacen que `tsc` falle si se olvida una.
 */
export interface AppEnvironment {
  /** Nombre del entorno; se muestra en el pie y en los reportes de error. */
  readonly name: 'development' | 'staging' | 'production';

  /**
   * Prefijo de la API. En desarrollo es una ruta relativa para que el proxy
   * de `ng serve` evite CORS y no exponga el host del backend en el bundle.
   */
  readonly apiBaseUrl: string;

  /** `true` solo en producción: desactiva trazas detalladas en consola. */
  readonly production: boolean;

  /** Habilita logs de depuración en consola. Debe ser `false` fuera de desarrollo. */
  readonly enableDebugLogs: boolean;

  /**
   * Minutos de inactividad antes de cerrar la sesión en el cliente.
   * No sustituye la expiración del token en el backend (F-03), la acompaña.
   */
  readonly sessionIdleTimeoutMinutes: number;
}
