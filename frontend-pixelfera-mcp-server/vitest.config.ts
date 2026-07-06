import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    globals: true,
    environment: 'node',
    // better-sqlite3 (native addon) segfaults under vitest's default worker-thread
    // pool on CI; forks run each test file in a child process, which is stable.
    pool: 'forks',
    include: ['tests/**/*.test.ts'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json', 'html'],
      exclude: [
        'node_modules/',
        'dist/',
        'tests/'
      ]
    }
  }
});
