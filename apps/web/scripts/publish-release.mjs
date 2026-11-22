/*
 * Publish one immutable browser release.
 *
 * Vite writes `dist/` with content-hashed assets. This script copies that exact
 * tree into `apps/web/releases/<id>/` and records `dist/release.json`. The API
 * resolves the manifest once at startup and serves only that release directory,
 * so building release B never replaces the files release A is serving.
 *
 * The id is derived from the entry assets themselves, not from a commit: a build
 * containing uncommitted changes gets its own id.
 */
import { createHash } from 'node:crypto'
import {
  cpSync,
  existsSync,
  mkdirSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const web = resolve(here, '..')
const dist = resolve(process.argv[2] ?? join(web, 'dist'))
const releases = join(web, 'releases')
const indexPath = join(dist, 'index.html')

if (!existsSync(indexPath)) {
  console.error('publish-release: dist/index.html is missing; run vite build first.')
  process.exit(1)
}

const html = readFileSync(indexPath, 'utf8')
const entryMatch = /<script[^>]+src="\/(assets\/[^"]+\.js)"/.exec(html)
const cssMatch = /<link[^>]+href="\/(assets\/[^"]+\.css)"/.exec(html)
if (!entryMatch) {
  console.error('publish-release: no module entry script found in dist/index.html.')
  process.exit(1)
}
const entryPath = entryMatch[1]
const cssPath = cssMatch?.[1] ?? ''
const entry = entryPath.split('/').pop()
const css = cssPath ? cssPath.split('/').pop() : ''

const hash = createHash('sha256')
hash.update(entryPath)
hash.update(readFileSync(join(dist, entryPath)))
if (cssPath) {
  hash.update(cssPath)
  hash.update(readFileSync(join(dist, cssPath)))
}
const id = hash.digest('hex').slice(0, 12)

// The API generation this bundle was built against. Reading it from the running
// source keeps the pair honest without a second hand-maintained constant.
const pyMain = readFileSync(resolve(web, '../../services/api/main.py'), 'utf8')
const api = Number(/^API_VERSION = (\d+)$/m.exec(pyMain)?.[1] ?? 0)
if (!api) {
  console.error('publish-release: could not read API_VERSION from services/api/main.py.')
  process.exit(1)
}

const target = join(releases, id)
if (!existsSync(join(target, 'index.html'))) {
  rmSync(target, { recursive: true, force: true })
  mkdirSync(target, { recursive: true })
  cpSync(indexPath, join(target, 'index.html'))
  cpSync(join(dist, 'assets'), join(target, 'assets'), { recursive: true })
}

const manifest = {
  schema: 1,
  id,
  entry,
  css,
  api,
  built: new Date().toISOString(),
  directory: `releases/${id}`,
}
writeFileSync(join(dist, 'release.json'), JSON.stringify(manifest, null, 2) + '\n')
console.log(
  `publish-release: ${id} -> apps/web/releases/${id} (entry ${entry}, API ${api})`,
)
