// Vitest config — pure-function unit tests only (tree building, path
// helpers). No DOM environment: nothing under test touches the document,
// and keeping it node-only also keeps Vitest's browser-mode surface (where
// its CVEs live) switched off.
import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts'],
  },
})
