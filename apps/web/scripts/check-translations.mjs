#!/usr/bin/env node
/**
 * Translation completeness gate.
 *
 * `tsc` already fails when `en.ts` is missing a key from `ja.ts` (it is typed as
 * `Record<TranslationKey, string>`), but CI also runs this check so a broken
 * build step or a dictionary switched to JSON cannot silently ship untranslated
 * strings. It reports missing keys and empty values in either direction.
 */
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const files = { ja: join(root, 'src/i18n/ja.ts'), en: join(root, 'src/i18n/en.ts') }
const entry = /^\s{2}'([^']+)':\s*(.*?),\s*$/gm

function readKeys(language, path) {
  const source = readFileSync(path, 'utf8')
  const keys = new Map()
  const duplicates = []
  for (const match of source.matchAll(entry)) {
    const [, key, value] = match
    if (keys.has(key)) duplicates.push(key)
    keys.set(key, value)
  }
  return { language, keys, duplicates }
}

const results = Object.entries(files).map(([language, path]) => readKeys(language, path))
const [base, other] = results
const problems = []

for (const result of results) {
  if (result.duplicates.length)
    problems.push(`${result.language}: duplicate key(s) ${result.duplicates.join(', ')}`)
  for (const [key, value] of result.keys)
    if (!value.replace(/^['"]|['"]$/g, '').trim())
      problems.push(`${result.language}: empty value for "${key}"`)
}

const missingIn = (from, to) => [...from.keys.keys()].filter((key) => !to.keys.has(key))
for (const key of missingIn(base, other)) problems.push(`en: missing key "${key}"`)
for (const key of missingIn(other, base)) problems.push(`ja: missing key "${key}"`)

if (problems.length) {
  console.error('Translation check failed:')
  for (const problem of problems) console.error('  - ' + problem)
  process.exit(1)
}

console.log(
  `Translation check passed: ${base.keys.size} keys in both ${base.language} and ${other.language}.`,
)
