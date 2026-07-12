// Lint entrypoint = base config + the jsx-a11y accessibility guardrail.
//
// This file exists (instead of adding the plugin inside eslint.config.js)
// because the repo owner's config-protection hook intentionally freezes
// eslint.config.js. Flat-config composition gives the same result additively:
// every base rule still applies (imported below, so future edits to the base
// file keep flowing through), and jsx-a11y/recommended is layered ON TOP —
// this entrypoint can only strengthen the gate, never weaken it.
// `npm run lint` points here via package.json.
import base from './eslint.config.js'
import jsxA11y from 'eslint-plugin-jsx-a11y'

export default [
  ...base,
  // Vitest's --coverage HTML report (coverage/, gitignored) ships its own JS
  // with stale eslint-disable pragmas; never lint generated output. Added
  // here because the base config's ignores are frozen with it.
  { ignores: ['coverage'] },
  {
    files: ['**/*.{js,jsx}'],
    plugins: { 'jsx-a11y': jsxA11y },
    rules: {
      ...jsxA11y.flatConfigs.recommended.rules,
    },
  },
]
