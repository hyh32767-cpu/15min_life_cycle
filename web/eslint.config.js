import js from '@eslint/js'
import pluginVue from 'eslint-plugin-vue'
import tseslint from 'typescript-eslint'

const browserGlobals = {
  window: 'readonly',
  document: 'readonly',
  console: 'readonly',
  fetch: 'readonly',
  setTimeout: 'readonly',
  clearTimeout: 'readonly',
  URL: 'readonly',
  navigator: 'readonly',
  MouseEvent: 'readonly',
  SVGSVGElement: 'readonly',
  HTMLElement: 'readonly',
  Event: 'readonly',
  KeyboardEvent: 'readonly',
  requestAnimationFrame: 'readonly',
  ResizeObserver: 'readonly',
  PointerEvent: 'readonly',
}

export default tseslint.config(
  {
    ignores: ['dist/**', 'coverage/**', 'playwright-report/**', 'test-results/**', 'node_modules/**'],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  ...pluginVue.configs['flat/recommended'],
  {
    files: ['**/*.vue'],
    languageOptions: {
      parserOptions: {
        parser: tseslint.parser,
      },
    },
  },
  {
    files: ['src/**/*.{ts,vue}', 'tests/**/*.ts'],
    languageOptions: {
      globals: browserGlobals,
    },
  },
)
