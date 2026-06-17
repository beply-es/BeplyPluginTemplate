#!/usr/bin/env node
import {
  cpSync,
  existsSync,
  mkdtempSync,
  mkdirSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from 'node:fs'
import { dirname, resolve } from 'node:path'
import { execFileSync } from 'node:child_process'
import { tmpdir } from 'node:os'

const root = process.cwd()
const args = new Map()
const flags = new Set()

for (let index = 2; index < process.argv.length; index++) {
  const arg = process.argv[index]
  if (!arg.startsWith('--')) {
    continue
  }

  const next = process.argv[index + 1]
  if (next && !next.startsWith('--')) {
    args.set(arg, next)
    index++
  } else {
    flags.add(arg)
  }
}

const apply = flags.has('--apply')
const allowDirty = flags.has('--allow-dirty')
const repo = args.get('--repo') || process.env.BEPLY_TEMPLATE_REPO || 'https://github.com/beply-es/BeplyPluginTemplate.git'
const templateRootArg = args.get('--template-root')
const targetRef = args.get('--ref') || process.env.BEPLY_TEMPLATE_REF || readLocalDefaultRef()

if (apply && !allowDirty && isGitDirty(root)) {
  console.error('ERROR: working tree has local changes. Commit/stash first or pass --allow-dirty.')
  process.exit(1)
}

let tempDir = ''
let templateRoot = templateRootArg ? resolve(templateRootArg) : ''

try {
  if (!templateRoot) {
    if (!targetRef) {
      console.error('ERROR: missing --ref and no defaultRef found in .beply/template-sync.json')
      process.exit(1)
    }

    tempDir = mkdtempSync(resolve(tmpdir(), 'beply-template-'))
    execFileSync('git', ['clone', '--depth', '1', '--branch', targetRef, repo, tempDir], {
      stdio: 'inherit',
    })
    templateRoot = tempDir
  }

  const policy = readJson(resolve(templateRoot, '.beply/template-sync.json'))
  const overwrite = unique(policy.overwrite || [])
  const createIfMissing = unique(policy.createIfMissing || [])
  const neverOverwrite = unique(policy.neverOverwrite || [])
  const operations = []

  for (const path of overwrite) {
    operations.push({ mode: 'overwrite', path })
  }

  for (const path of createIfMissing) {
    operations.push({ mode: 'create-if-missing', path })
  }

  printPlan({ templateRoot, targetRef, overwrite, createIfMissing, neverOverwrite })

  if (!apply) {
    console.log('Dry-run only. Re-run with --apply to copy safe template files.')
    process.exit(0)
  }

  for (const operation of operations) {
    const source = resolve(templateRoot, operation.path)
    const destination = resolve(root, operation.path)

    if (!existsSync(source)) {
      console.warn(`WARN: source missing, skipped: ${operation.path}`)
      continue
    }

    if (operation.mode === 'create-if-missing' && existsSync(destination)) {
      console.log(`skip existing ${operation.path}`)
      continue
    }

    mkdirSync(dirname(destination), { recursive: true })
    cpSync(source, destination, { recursive: true })
    console.log(`${operation.mode} ${operation.path}`)
  }

  updateTemplateLock({ repo, targetRef, templateRoot })
  console.log('Template sync complete. Review git diff and run tests.')
} finally {
  if (tempDir) {
    rmSync(tempDir, { recursive: true, force: true })
  }
}

function readLocalDefaultRef() {
  const policyPath = resolve(root, '.beply/template-sync.json')
  if (!existsSync(policyPath)) {
    return ''
  }

  return readJson(policyPath).defaultRef || ''
}

function readJson(path) {
  try {
    return JSON.parse(readFileSync(path, 'utf8'))
  } catch (error) {
    console.error(`ERROR: cannot read JSON ${path}: ${error.message}`)
    process.exit(1)
  }
}

function unique(values) {
  return [...new Set(values.filter((value) => typeof value === 'string' && value.trim() !== ''))]
}

function isGitDirty(cwd) {
  try {
    const output = execFileSync('git', ['status', '--porcelain'], {
      cwd,
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'ignore'],
    })
    return output.trim() !== ''
  } catch {
    return false
  }
}

function gitHead(cwd) {
  try {
    return execFileSync('git', ['rev-parse', 'HEAD'], {
      cwd,
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'ignore'],
    }).trim()
  } catch {
    return ''
  }
}

function printPlan({ templateRoot, targetRef, overwrite, createIfMissing, neverOverwrite }) {
  console.log(`Template source: ${templateRoot}`)
  console.log(`Template ref: ${targetRef || '(local)'}`)
  console.log(`Overwrite (${overwrite.length}):`)
  for (const path of overwrite) {
    console.log(`  - ${path}`)
  }
  console.log(`Create if missing (${createIfMissing.length}):`)
  for (const path of createIfMissing) {
    console.log(`  - ${path}`)
  }
  console.log(`Never overwrite (${neverOverwrite.length}):`)
  for (const path of neverOverwrite) {
    console.log(`  - ${path}`)
  }
}

function updateTemplateLock({ repo, targetRef, templateRoot }) {
  const lockPath = resolve(root, '.beply/template-lock.json')
  const sourceLockPath = resolve(templateRoot, '.beply/template-lock.json')
  const sourceLock = existsSync(sourceLockPath) ? readJson(sourceLockPath) : {}
  const lock = {
    schema: 1,
    template: sourceLock.template || repo,
    version: sourceLock.version || targetRef.replace(/^v/, ''),
    ref: targetRef || sourceLock.ref || '',
    commit: gitHead(templateRoot),
    syncedAt: new Date().toISOString(),
    mode: 'initial-scaffold-plus-controlled-tooling-sync',
  }

  mkdirSync(dirname(lockPath), { recursive: true })
  writeFileSync(lockPath, `${JSON.stringify(lock, null, 2)}\n`)
}
