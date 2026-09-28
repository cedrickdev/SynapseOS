import { defineConfig, devices } from '@playwright/test'

const e2ePort = process.env.SYNAPSEOS_E2E_PORT ?? '33100'
const e2eBaseUrl = `http://localhost:${e2ePort}`

export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: false,
  retries: 0,
  timeout: 30_000,
  use: {
    baseURL: e2eBaseUrl,
    trace: 'retain-on-failure'
  },
  projects: [
    { name: 'desktop-chromium', use: { ...devices['Desktop Chrome'] } },
    { name: 'mobile-chromium', use: { ...devices['Pixel 7'] } }
  ],
  webServer: {
    command: `SYNAPSEOS_E2E_AUTH=1 pnpm exec nuxt dev --host 127.0.0.1 --port ${e2ePort}`,
    url: e2eBaseUrl,
    reuseExistingServer: process.env.SYNAPSEOS_E2E_DASHBOARD === '1',
    timeout: 120_000
  }
})
