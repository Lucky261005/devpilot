import { execFileSync } from 'node:child_process'
import { mkdirSync } from 'node:fs'
import { resolve } from 'node:path'

// Build the sample archive from the fixture so the test uploads exactly what is in the repo.
export default function globalSetup() {
  const out = resolve(import.meta.dirname, '../../test-results')
  mkdirSync(out, { recursive: true })
  const fixture = resolve(
    import.meta.dirname,
    '../../../fixtures/sample_repositories/inventory_service',
  )
  const script = `
import pathlib, sys, zipfile
src, dest = pathlib.Path(sys.argv[1]), sys.argv[2]
with zipfile.ZipFile(dest, "w") as z:
    for p in src.rglob("*"):
        if p.is_file() and "__pycache__" not in p.parts:
            z.write(p, "inventory_service/" + p.relative_to(src).as_posix())
`
  const backend = resolve(import.meta.dirname, '../../../backend')
  execFileSync('uv', ['run', 'python', '-c', script, fixture, resolve(out, 'sample.zip')], {
    cwd: backend,
  })
}
