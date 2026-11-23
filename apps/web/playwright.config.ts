import { defineConfig } from '@playwright/test'
import { existsSync } from 'node:fs'
import { resolve } from 'node:path'
const windows = process.platform === 'win32'
const edge = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
const python = process.env.SEAL_TEST_PYTHON || resolve('../..', windows ? '.venv/Scripts/python.exe' : '.venv/bin/python')
const port = process.env.SEAL_TEST_PORT || '8876'
export default defineConfig({
  testDir: './tests',
  timeout: 80000,
  workers: 1,
  fullyParallel: false,
  use: {
    baseURL: 'http://127.0.0.1:' + port,
    viewport: { width: 1440, height: 960 },
    launchOptions: {
      executablePath: process.env.SEAL_BROWSER || (existsSync(edge) ? edge : undefined),
      args: ['--enable-webgl', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
    },
    screenshot: 'only-on-failure',
  },
  webServer: {
    command: '"' + python + '" ../../scripts/serve.py --test-data --port ' + port,
    url: 'http://127.0.0.1:' + port + '/api/projects',
    reuseExistingServer: process.env.SEAL_REUSE_TEST_SERVER === '1',
    timeout: 60000,
  },
})
