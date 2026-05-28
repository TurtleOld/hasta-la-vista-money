import js from '@eslint/js';
import globals from 'globals';

export default [
  {
    ignores: [
      'static/js/dist/**',
      'static/js/**/*.min.js',
      'static/js/driver.js',
      'static/js/tex-mml-chtml.js',
    ],
  },
  js.configs.recommended,
  {
    files: ['static/js/**/*.js'],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'module',
      globals: {
        ...globals.browser,
        Alpine: 'readonly',
        Chart: 'readonly',
        htmx: 'readonly',
      },
    },
    rules: {
      'no-unused-vars': [
        'error',
        {
          argsIgnorePattern: '^_',
          caughtErrorsIgnorePattern: '^_',
        },
      ],
    },
  },
  {
    files: ['*.mjs'],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'module',
      globals: globals.node,
    },
  },
];
