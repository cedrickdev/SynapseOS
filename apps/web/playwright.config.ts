import { defineConfig, devices } from '@playwright/test'

const e2ePort = process.env.SYNAPSEOS_E2E_PORT ?? '3000'
const e2eBaseUrl = `http://127.0.0.1:${e2ePort}`

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
    command: `pnpm exec nuxt dev --host 127.0.0.1 --port ${e2ePort}`,
    url: e2eBaseUrl,
    reuseExistingServer: process.env.SYNAPSEOS_E2E_DASHBOARD !== '1',
    timeout: 120_000
  }
})
