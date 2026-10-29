// @ts-check
/**
 * ESLint (flat config) del frontend.
 *
 * Qué cubre y por qué:
 *  - `angular-eslint`: reglas del framework (ciclo de vida, plantillas, accesibilidad).
 *  - `typescript-eslint` con `recommendedTypeChecked`: usa el type-checker, de modo
 *    que detecta promesas sin `await`, `any` que se escapa y comparaciones imposibles.
 *  - `eslint-plugin-security`: heurísticas de código peligroso (OWASP Top 10:2025 A03/A05).
 *
 * Reglas elevadas a `error` a propósito (no son estilo, son defectos en una app bancaria):
 *  - `no-console`: la consola del navegador la lee el usuario; aquí circulan saldos y PAN.
 *  - `@typescript-eslint/no-floating-promises`: una llamada HTTP sin manejar puede perder
 *    silenciosamente el resultado de una operación de dinero.
 *  - `no-restricted-syntax` sobre `localStorage`/`sessionStorage`: guardar tokens ahí los
 *    expone a XSS. La decisión de dónde vive el token es de F-03; hasta entonces se bloquea.
 *
 * Referencias:
 *  - https://github.com/angular-eslint/angular-eslint
 *  - https://typescript-eslint.io/getting-started/typed-linting/
 */
import eslint from '@eslint/js';
import tseslint from 'typescript-eslint';
import angular from 'angular-eslint';
import security from 'eslint-plugin-security';

export default tseslint.config(
  {
    // Artefactos generados: nunca se lintean.
    ignores: ['dist/**', 'coverage/**', 'reports/**', 'node_modules/**', '.angular/**'],
  },
  {
    files: ['**/*.ts'],
    extends: [
      eslint.configs.recommended,
      ...tseslint.configs.recommendedTypeChecked,
      ...tseslint.configs.stylisticTypeChecked,
      ...angular.configs.tsRecommended,
      security.configs.recommended,
    ],
    languageOptions: {
      parserOptions: {
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
      },
    },
    processor: angular.processInlineTemplates,
    rules: {
      '@angular-eslint/directive-selector': [
        'error',
        { type: 'attribute', prefix: 'app', style: 'camelCase' },
      ],
      '@angular-eslint/component-selector': [
        'error',
        { type: 'element', prefix: 'app', style: 'kebab-case' },
      ],

      // --- Código seguro ---
      'no-console': 'error',
      'no-eval': 'error',
      'no-implied-eval': 'error',
      '@typescript-eslint/no-explicit-any': 'error',
      '@typescript-eslint/no-floating-promises': 'error',
      '@typescript-eslint/no-misused-promises': 'error',
      '@typescript-eslint/no-unsafe-assignment': 'error',
      '@typescript-eslint/no-unsafe-member-access': 'error',
      '@typescript-eslint/no-unsafe-return': 'error',
      '@typescript-eslint/no-unsafe-call': 'error',
      '@typescript-eslint/no-unsafe-argument': 'error',
      '@typescript-eslint/no-non-null-assertion': 'error',
      'no-restricted-syntax': [
        'error',
        {
          selector: 'MemberExpression[object.name=/^(localStorage|sessionStorage)$/]',
          message:
            'No usar localStorage/sessionStorage: es accesible desde cualquier XSS. El almacenamiento del token se define en F-03.',
        },
        {
          selector: "CallExpression[callee.property.name='bypassSecurityTrust']",
          message:
            'bypassSecurityTrust* desactiva el saneado de Angular. Si de verdad es necesario, documentar el motivo y pedir revisión de seguridad en el PR.',
        },
      ],
      '@typescript-eslint/no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
      ],

      // --- Código limpio ---
      eqeqeq: ['error', 'always'],
      'prefer-const': 'error',
      'no-var': 'error',
      complexity: ['error', 12],
      'max-depth': ['error', 4],
      'max-lines-per-function': ['error', { max: 60, skipBlankLines: true, skipComments: true }],
      '@typescript-eslint/explicit-function-return-type': [
        'error',
        { allowExpressions: true, allowHigherOrderFunctions: true },
      ],
      '@typescript-eslint/consistent-type-imports': 'error',
    },
  },
  {
    // En las pruebas se relajan las reglas que solo estorban al escribir fixtures.
    files: ['**/*.spec.ts'],
    rules: {
      'max-lines-per-function': 'off',
      '@typescript-eslint/no-non-null-assertion': 'off',
      '@typescript-eslint/no-unsafe-assignment': 'off',
      'security/detect-object-injection': 'off',
    },
  },
  {
    files: ['**/*.html'],
    extends: [...angular.configs.templateRecommended, ...angular.configs.templateAccessibility],
    rules: {},
  },
);
