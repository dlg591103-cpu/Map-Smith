import path from 'node:path'
import { defineConfig } from '@playwright/test'

const projectRoot = path.resolve(process.cwd(), '..')

export default defineConfig({
  testDir: './e2e',
  timeout: 120_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL: 'http://127.0.0.1:8501',
    headless: true,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  webServer: {
    command: '.venv\\Scripts\\python.exe -m mapsmith --port 8501',
    cwd: projectRoot,
    url: 'http://127.0.0.1:8501/api/health',
    reuseExistingServer: true,
    timeout: 120_000,
    env: { PYTHONPATH: 'src' },
  },
})