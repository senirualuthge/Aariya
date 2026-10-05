import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import { defineConfig, globalIgnores } from 'eslint/config'

const RULES = {
  // Unused *bindings* are pre-existing debt in this tree (~4.4k of them, mostly
  // the generated GEV data modules). Kept as warnings so `npm run lint` gates on
  // real breakage instead of a backlog nobody has triaged.
  // Deliberate: the radio/space-weather parsers filter control characters out
  // of upstream text with explicit ranges like /[\x00-\x1f]/.
  'no-control-regex': 'off',
  // Several entry points carry `/* global process */` banners; the built-in
  // global is already provided, so don't report the banner as a redeclaration.
  'no-redeclare': ['error', { builtinGlobals: false }],
  'no-unused-vars': [
    'warn',
    { varsIgnorePattern: '^[A-Z_]', argsIgnorePattern: '^_', args: 'after-used' },
  ],
}

export default defineConfig([
  globalIgnores([
    'dist',
    'node_modules',
    'venv',
    'public',
    'mobile/build',
    'coverage',
    'qa-shots',
  ]),
  {
    // Renderer/app sources: browser globals plus the Node surface Electron
    // still exposes to bundled app code (process.env.*, Buffer).
    files: ['src/**/*.{js,jsx}'],
    extends: [
      js.configs.recommended,
      // v5.2 ships `recommended`/`recommended-legacy` in the eslintrc shape
      // (plugins as an array of strings). `recommended-latest` is the flat
      // config variant, same two rules.
      reactHooks.configs['recommended-latest'],
    ],
    plugins: { 'react-refresh': reactRefresh },
    languageOptions: {
      ecmaVersion: 'latest',
      globals: { ...globals.browser, ...globals.node },
      parserOptions: {
        ecmaVersion: 'latest',
        ecmaFeatures: { jsx: true },
        sourceType: 'module',
      },
    },
    rules: {
      ...RULES,
      // eslint-plugin-react-refresh 0.4.x still ships its `configs.vite` in the
      // eslintrc shape, so the rule is enabled by hand against the plugin
      // registered above (same rule set that config carries).
      'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],
    },
  },
  {
    // Build config + Node tooling: no JSX, Node globals.
    files: ['*.js', '*.cjs', '*.mjs'],
    languageOptions: {
      ecmaVersion: 'latest',
      globals: globals.node,
      parserOptions: { sourceType: 'module' },
    },
    extends: [js.configs.recommended],
    rules: RULES,
  },
  {
    // GEV QA harnesses are hybrid: Node drives the CLI/puppeteer side, and the
    // same files hold `page.evaluate` bodies that legitimately touch window,
    // document and DOM APIs inside the browser.
    files: ['scripts/**/*.{js,mjs,cjs}'],
    languageOptions: {
      ecmaVersion: 'latest',
      globals: { ...globals.node, ...globals.browser },
      parserOptions: { sourceType: 'module' },
    },
    extends: [js.configs.recommended],
    rules: RULES,
  },
  {
    // CommonJS Node entry points (Electron main/preload) must not be parsed as ESM.
    files: ['**/*.cjs'],
    languageOptions: {
      ecmaVersion: 'latest',
      globals: { ...globals.node, ...globals.commonjs },
      sourceType: 'commonjs',
    },
  },
])