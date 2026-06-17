#!/usr/bin/env node
import { cpSync, existsSync, mkdirSync, readFileSync } from 'node:fs'
import { basename, resolve } from 'node:path'

const root = process.cwd()
const apply = process.argv.includes('--apply')
const docsRootArgIndex = process.argv.indexOf('--docs-root')
const docsRoot = docsRootArgIndex >= 0
  ? process.argv[docsRootArgIndex + 1]
  : process.env.BEPLY_DOCS_REPO_PATH

const targetDir = process.env.BEPLY_DOCS_PLUGIN_TARGET_DIR || 'src/content/help/plugins'
const ini = parseIni('facturascripts.ini')
const pluginSlug = (ini.name || basename(root)).toLowerCase()
const source = resolve(root, 'docs/user')

if (!existsSync(source)) {
  console.error('ERROR: docs/user does not exist')
  process.exit(1)
}

if (!docsRoot) {
  console.log('Docs sync dry-run: set BEPLY_DOCS_REPO_PATH or pass --docs-root to apply against a docs checkout.')
  printPlan('(missing docs root)')
  process.exit(apply ? 1 : 0)
}

const destination = resolve(docsRoot, targetDir, pluginSlug)
printPlan(destination)

if (!apply) {
  console.log('Dry-run only. Re-run with --apply to copy files.')
  process.exit(0)
}

mkdirSync(destination, { recursive: true })
cpSync(source, destination, { recursive: true })
console.log(`Copied ${source} -> ${destination}`)

function printPlan(destination) {
  const impact = JSON.parse(readFileSync(resolve(root, 'docs/docs-sync/impact-map.json'), 'utf8'))
  console.log(`Plugin: ${ini.name}`)
  console.log(`Source: ${source}`)
  console.log(`Destination: ${destination}`)
  console.log(`Impacts: ${(impact.impacts || []).map((item) => item.id).join(', ')}`)
}

function parseIni(path) {
  const data = readFileSync(resolve(root, path), 'utf8')
  const result = {}
  for (const line of data.split(/\r?\n/)) {
    const match = line.match(/^\s*([A-Za-z0-9_]+)\s*=\s*(.*?)\s*$/)
    if (match) {
      result[match[1]] = match[2].replace(/^['"]|['"]$/g, '')
    }
  }
  return result
}
