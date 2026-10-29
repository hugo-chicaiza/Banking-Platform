/**
 * Configuración base del runner de pruebas (Vitest) que usa `@angular/build:unit-test`.
 *
 * El builder de Angular ya resuelve la compilación, los polyfills y el TestBed.
 * Este archivo solo añade lo que la CLI no expone como opción: los umbrales de
 * cobertura y los formatos de reporte que consumen el CI y SonarQube.
 *
 * Se carga porque `angular.json` declara `"runnerConfig": true` en el target `test`.
 * Referencia: https://angular.dev/guide/testing/unit-tests
 */
import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    // Las pruebas no deben depender del orden de ejecución entre archivos.
    isolate: true,
    // Un `it` que tarda más de 10 s en una prueba unitaria es un defecto, no lentitud.
    testTimeout: 10_000,
    coverage: {
      provider: 'v8',
      reportsDirectory: './coverage',
      reporter: ['text-summary', 'lcovonly', 'cobertura', 'json-summary'],
      // Umbral acordado para la Épica 0. F-06 puede subirlo cuando haya
      // más superficie de código; bajarlo requiere acuerdo del equipo.
      thresholds: {
        lines: 80,
        statements: 80,
        functions: 80,
        branches: 70,
      },
    },
  },
});
