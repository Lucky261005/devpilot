// Writes dist/login.html: the built index.html with the front screen rendered into #root.
// Vite preview (and most static hosts) serve /login from login.html; other routes keep the
// empty index.html and render in the browser as before.
import { readFileSync, rmSync, writeFileSync } from 'node:fs'
import { pathToFileURL } from 'node:url'

const { render } = await import(pathToFileURL('dist-ssr/entry-prerender.js').href)
const shell = readFileSync('dist/index.html', 'utf8')
const slot = '<div id="root"></div>'
if (!shell.includes(slot)) throw new Error('dist/index.html has no empty #root to fill')
writeFileSync('dist/login.html', shell.replace(slot, `<div id="root">${render()}</div>`))
rmSync('dist-ssr', { recursive: true, force: true })
console.log('prerendered dist/login.html')
