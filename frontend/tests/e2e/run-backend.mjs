// Starts a throwaway backend for end-to-end tests: fresh DB, migrations, then uvicorn.
import { execFileSync, spawn } from 'node:child_process'
import { rmSync } from 'node:fs'
import { resolve } from 'node:path'

const backend = resolve(import.meta.dirname, '../../../backend')
const env = {
  ...process.env,
  DEVPILOT_DATABASE_URL: 'sqlite:///./e2e.db',
  DEVPILOT_DATA_DIR: './e2e-data',
  ANTHROPIC_API_KEY: '',
  DEVPILOT_ALLOWED_LOCAL_ROOTS: '',
}
rmSync(resolve(backend, 'e2e.db'), { force: true })
rmSync(resolve(backend, 'e2e-data'), { recursive: true, force: true })
execFileSync('uv', ['run', 'alembic', 'upgrade', 'head'], { cwd: backend, env, stdio: 'inherit' })
const p = spawn('uv', ['run', 'uvicorn', 'app.main:app', '--port', '8001'], {
  cwd: backend,
  env,
  stdio: 'inherit',
})
process.on('SIGTERM', () => p.kill())
process.on('SIGINT', () => p.kill())
