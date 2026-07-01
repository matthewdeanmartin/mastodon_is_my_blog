import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    globals: true,
    environment: 'jsdom',
    include: ['src/**/*.spec.ts'],
    // Integration specs need a live backend; run them via `npm run test:integration`.
    exclude: ['**/node_modules/**', 'src/**/*.integration.spec.ts'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json', 'html'],
      include: ['src/app/*.service.ts', 'src/app/api.service.ts'],
    },
  },
});
