/*
 * Source-quality check for mojibake in user-facing browser sources.
 *
 * These byte sequences only appear when UTF-8 text has been decoded as
 * Windows-1252/Latin-1. A legitimate question mark, operator or Unicode
 * character is not flagged; only known corruption sequences are.
 */
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { dirname, join, relative, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..', 'src')
const BAD = ['Â·', 'â€”', 'â€“', 'â‚¬', 'Ã©', 'Ã¨', 'Ã¼', 'ï¿½']
const EXTENSIONS = new Set(['.ts', '.tsx', '.css'])

function walk(directory) {
  const files = []
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name)
    if (entry.isDirectory()) files.push(...walk(path))
    else if (entry.isFile() && EXTENSIONS.has(path.slice(path.lastIndexOf('.')))) {
      files.push(path)
    }
  }
  return files
}

const problems = []
for (const path of walk(root)) {
  const text = readFileSync(path, 'utf8')
  for (const token of BAD) {
    if (!text.includes(token)) continue
    const line = text.slice(0, text.indexOf(token)).split('\n').length
    problems.push(`${relative(root, path)}:${line} contains ${JSON.stringify(token)}`)
  }
  // A replacement character is never intentional in these sources.
  if (text.includes('\uFFFD')) {
    problems.push(`${relative(root, path)} contains U+FFFD`)
  }
}

if (problems.length) {
  console.error('Encoding check failed:')
  for (const problem of problems) console.error('  ' + problem)
  process.exit(1)
}
console.log(`Encoding check passed: ${walk(root).length} source files have no known mojibake.`)
