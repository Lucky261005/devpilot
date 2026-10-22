import { defineConfig } from '@playwright/test'

// Boots an isolated backend (fresh SQLite DB on port 8001) and a frontend pointed at it.

export default defineConfig({
  testDir: './tests/e2e',
  timeout: 60_000,
  globalSetup: './tests/e2e/global-setup.ts',
  use: { baseURL: 'http://127.0.0.1:5174', trace: 'retain-on-failure' },
  webServer: [
    {
      command: `node tests/e2e/run-backend.mjs`,
      url: 'http://127.0.0.1:8001/api/health',
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command: 'npx vite --host 127.0.0.1 --port 5174 --strictPort',
      url: 'http://127.0.0.1:5174',
      reuseExistingServer: false,
      env: { DEVPILOT_API: 'http://127.0.0.1:8001' },
    },
  ],
})
