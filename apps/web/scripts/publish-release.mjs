/*
 * Publish one immutable, verified browser release.
 *
 * Vite writes `dist/` with content-hashed assets. This script stages the whole
 * tree, verifies every file the browser entry references, hashes the complete
 * file manifest and only then atomically publishes it. A manifest is written to
 * `dist/release.json` only after the published directory has been re-verified.
 *
 * The release id is the hash of the complete file manifest, not a commit: a
 * build containing uncommitted changes gets its own identity. A release that is
 * already complete is never rewritten, so a running instance keeps its files.
 */
import { createHash } from 'node:crypto'
import {
  cpSync,
  existsSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  renameSync,
  rmSync,
  statSync,
  writeFileSync,
} from 'node:fs'
import { dirname, join, relative, resolve, sep } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const web = resolve(here, '..')
const dist = resolve(process.argv[2] ?? join(web, 'dist'))
const releases = join(web, 'releases')
const indexPath = join(dist, 'index.html')

function fail(message) {
  console.error('publish-release: ' + message)
  process.exit(1)
}

function sha256(path) {
  return createHash('sha256').update(readFileSync(path)).digest('hex')
}

function walk(root) {
  const out = []
  for (const name of readdirSync(root, { withFileTypes: true })) {
    const path = join(root, name.name)
    if (name.isDirectory()) out.push(...walk(path))
    else if (name.isFile()) out.push(path)
  }
  return out.sort()
}

function fileManifest(root) {
  return walk(root)
    .map((path) => {
      const rel = relative(root, path).split(sep).join('/')
      return { path: rel, size: statSync(path).size, sha256: sha256(path) }
    })
    // The manifest describes the release; it cannot include its own hash.
    .filter((file) => file.path !== 'manifest.json')
    .sort((a, b) => (a.path < b.path ? -1 : a.path > b.path ? 1 : 0))
}

function treeHash(files) {
  const text = files.map((f) => `${f.path}:${f.size}:${f.sha256}`).join('\n')
  return createHash('sha256').update(text).digest('hex')
}

if (!existsSync(indexPath)) fail('dist/index.html is missing; run vite build first.')

const html = readFileSync(indexPath, 'utf8')
const entryMatch = /<script[^>]+src="\/(assets\/[^"]+\.js)"/.exec(html)
const cssMatch = /<link[^>]+href="\/(assets\/[^"]+\.css)"/.exec(html)
if (!entryMatch) fail('no module entry script found in dist/index.html.')
const entryPath = entryMatch[1]
const cssPath = cssMatch?.[1] ?? ''
const entry = entryPath.split('/').pop()
const css = cssPath ? cssPath.split('/').pop() : ''

// Every absolute local reference in the entry document must exist before we
// even stage the release.
const referenced = [...html.matchAll(/(?:src|href)="\/([^"]+)"/g)].map((m) => m[1])
for (const rel of referenced) {
  if (!existsSync(join(dist, rel)) || !statSync(join(dist, rel)).isFile()) {
    fail(`index.html references a missing file: ${rel}`)
  }
}
for (const required of [entryPath, cssPath].filter(Boolean)) {
  if (!existsSync(join(dist, required))) fail(`required release file is missing: ${required}`)
}
if (!existsSync(join(dist, 'assets'))) fail('dist/assets is missing; the build is incomplete.')

const pyMain = readFileSync(resolve(web, '../../services/api/main.py'), 'utf8')
const api = Number(/^API_VERSION = (\d+)$/m.exec(pyMain)?.[1] ?? 0)
if (!api) fail('could not read API_VERSION from services/api/main.py')

mkdirSync(releases, { recursive: true })
const staging = join(releases, `.staging-${process.pid}-${Date.now()}`)
rmSync(staging, { recursive: true, force: true })
mkdirSync(staging, { recursive: true })

try {
  // Stage the complete built tree, excluding the pointer manifest.
  cpSync(dist, staging, {
    recursive: true,
    filter: (source) => resolve(source) !== resolve(dist, 'release.json'),
  })

  const files = fileManifest(staging)
  const tree = treeHash(files)
  const id = tree.slice(0, 12)
  const built = new Date().toISOString()
  const manifest = {
    schema: 2,
    id,
    entry,
    css,
    api,
    built,
    tree,
    files,
    directory: `releases/${id}`,
  }
  writeFileSync(join(staging, 'manifest.json'), JSON.stringify(manifest, null, 2) + '\n')

  const target = join(releases, id)
  const targetManifest = join(target, 'manifest.json')
  let publish = true
  if (existsSync(targetManifest)) {
    try {
      const existing = JSON.parse(readFileSync(targetManifest, 'utf8'))
      if (existing.tree === tree && existing.id === id) publish = false
    } catch {
      // A torn manifest is repaired below.
    }
  }

  if (publish) {
    if (existsSync(target)) {
      // Incomplete or mismatched prior publication: preserve it for diagnosis,
      // then replace it with a verified staging tree.
      const quarantine = join(
        releases,
        `.quarantine-${id}-${Date.now()}`,
      )
      renameSync(target, quarantine)
      console.warn(`publish-release: quarantined incomplete ${id} -> ${quarantine}`)
    }
    renameSync(staging, target)
  } else {
    rmSync(staging, { recursive: true, force: true })
  }

  // Re-verify the published directory before pointing dist at it.
  const published = fileManifest(target)
  if (treeHash(published) !== tree) fail(`published release ${id} failed verification`)
  for (const file of published) {
    if (!existsSync(join(target, file.path))) fail(`published file vanished: ${file.path}`)
  }
  if (!existsSync(join(target, entryPath))) fail(`published entry vanished: ${entryPath}`)

  writeFileSync(
    join(dist, 'release.json'),
    JSON.stringify(
      { ...manifest, directory: `releases/${id}` },
      null,
      2,
    ) + '\n',
  )
  console.log(
    `publish-release: ${id} -> apps/web/releases/${id} ` +
      `(${published.length} files, entry ${entry}, API ${api})`,
  )
} catch (error) {
  rmSync(staging, { recursive: true, force: true })
  fail(String(error && error.message ? error.message : error))
}
