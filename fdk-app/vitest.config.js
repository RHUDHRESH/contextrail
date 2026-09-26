import { defineConfig } from 'vitest/config';

// Default environment is node; tests that touch the DOM opt into jsdom with a
// `@vitest-environment jsdom` docblock.
export default defineConfig({
  // Inline (empty) PostCSS config: stops Vite from picking up the repo root's Next.js postcss.config.mjs.
  css: { postcss: {} },
  test: {
    globals: true,
    environment: 'node',
    include: ['tests/**/*.test.js'],
    coverage: {
      provider: 'v8',
      reportsDirectory: 'coverage/unit',
      reporter: ['json', 'text'],
      include: ['app/scripts/**/*.js', 'server/**/*.js']
    }
  }
});
