import { defineConfig } from 'vitest/config'

// Unit tests for the pure logic extracted from App.tsx (Phase 6). The libs are
// framework-free, so the lightweight `node` environment is enough; component
// smoke tests (jsdom + Testing Library) are a follow-up.
export default defineConfig({
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts'],
    coverage: {
      provider: 'v8',
      include: ['src/lib/**', 'src/constants.ts'],
      reporter: ['text', 'html'],
    },
  },
})
