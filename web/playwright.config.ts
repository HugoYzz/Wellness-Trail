import path from 'node:path'

import { defineConfig, devices } from '@playwright/test'

const apiPort = 18001
const webPort = 15173
const e2eDatabase = path.resolve('test-results', `kangji-e2e-${process.pid}.sqlite3`)
const python = process.platform === 'win32'
  ? `"${path.resolve('../server/.venv/Scripts/python.exe')}"`
  : 'python'

export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['html', { open: 'never' }], ['list']] : 'list',
  use: {
    baseURL: `http://127.0.0.1:${webPort}`,
    trace: 'on-first-retry',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  webServer: [
    {
      command: `${python} -m uvicorn app.main:app --host 127.0.0.1 --port ${apiPort}`,
      cwd: path.resolve('../server'),
      url: `http://127.0.0.1:${apiPort}/api/health`,
      reuseExistingServer: false,
      timeout: 120_000,
      env: {
        KANGJI_DB_PATH: e2eDatabase,
        LLM_DEFAULT_PROVIDER: 'mock',
        MOCK_STREAM_DELAY_MS: '700',
        RAG_VECTOR_ENABLED: '0',
      },
    },
    {
      command: `npm run dev -- --host 127.0.0.1 --port ${webPort}`,
      cwd: path.resolve('.'),
      url: `http://127.0.0.1:${webPort}`,
      reuseExistingServer: false,
      timeout: 120_000,
      env: {
        VITE_API_TARGET: `http://127.0.0.1:${apiPort}`,
      },
    },
  ],
})
