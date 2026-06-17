#!/usr/bin/env node
import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { execFileSync } from 'node:child_process'

const root = process.cwd()
const requireAi = process.argv.includes('--require-ai')
const errors = []

function fail(message) {
  errors.push(message)
}

function readJson(path) {
  const absolute = resolve(root, path)
  if (!existsSync(absolute)) {
    fail(`Missing ${path}`)
    return {}
  }

  try {
    return JSON.parse(readFileSync(absolute, 'utf8'))
  } catch (error) {
    fail(`Invalid JSON in ${path}: ${error.message}`)
    return {}
  }
}

function changedFiles() {
  const base = process.env.DOCS_AUDIT_BASE_REF || 'origin/main'
  const collected = new Set()

  function collect(args) {
    try {
      const output = execFileSync('git', args, {
        cwd: root,
        encoding: 'utf8',
        stdio: ['ignore', 'pipe', 'ignore'],
      })
      for (const file of output.split(/\r?\n/).filter(Boolean)) {
        collected.add(file)
      }
    } catch {
      // Ignore unavailable refs in local scaffolding checkouts.
    }
  }

  collect(['diff', '--name-only', `${base}...HEAD`])
  collect(['diff', '--name-only'])
  collect(['diff', '--name-only', '--cached'])
  collect(['ls-files', '--others', '--exclude-standard'])

  if (collected.size > 0) {
    return [...collected]
  }

  try {
    return execFileSync('git', ['show', '--name-only', '--pretty=format:', 'HEAD'], {
      cwd: root,
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'ignore'],
    }).split(/\r?\n/).filter(Boolean)
  } catch {
    return []
  }
}

const functionalPattern = /^(Controller|Extension|Lib|Model|Table|View|XMLView|Assets|Tools|Init\.php|facturascripts\.ini)/
const docsPattern = /^(docs|README\.md|CHANGELOG\.md)/

const files = changedFiles()
const functionalChanges = files.filter((file) => functionalPattern.test(file))
const docsChanges = files.filter((file) => docsPattern.test(file))

const impactMap = readJson('docs/docs-sync/impact-map.json')
const publishedPages = readJson('docs/docs-sync/published-pages.json')
const impacts = Array.isArray(impactMap.impacts) ? impactMap.impacts : []
const pages = Array.isArray(publishedPages.pages) ? publishedPages.pages : []

if (functionalChanges.length > 0 && impacts.length === 0) {
  fail('Functional changes detected but docs impact map has no entries')
}

for (const impact of impacts) {
  if (!impact.id) {
    fail('Docs impact entry without id')
    continue
  }
  if (!impact.basePage?.path) {
    fail(`Docs impact ${impact.id} missing basePage.path`)
  }
  if (!impact.pluginPage?.path) {
    fail(`Docs impact ${impact.id} missing pluginPage.path`)
  } else if (!existsSync(resolve(root, impact.pluginPage.path))) {
    fail(`Docs impact ${impact.id} references missing plugin page ${impact.pluginPage.path}`)
  }
  if (!Array.isArray(impact.surfaces) || impact.surfaces.length === 0) {
    fail(`Docs impact ${impact.id} must list affected surfaces`)
  }
  if (!impact.changes || !Array.isArray(impact.changes.actions) || !Array.isArray(impact.changes.flows)) {
    fail(`Docs impact ${impact.id} must describe actions and flows`)
  }
  if (!Array.isArray(impact.tests) || impact.tests.length === 0) {
    fail(`Docs impact ${impact.id} must link tests`)
  }
  if (!pages.some((page) => page.id === impact.id && page.publishedUrl)) {
    fail(`Docs impact ${impact.id} has no published page URL`)
  }
}

if (functionalChanges.length > 0 && docsChanges.length === 0) {
  fail(`Functional changes need docs changes. Functional files: ${functionalChanges.join(', ')}`)
}

if (errors.length > 0) {
  for (const error of errors) {
    console.error(`ERROR: ${error}`)
  }
  process.exit(1)
}

if (requireAi) {
  await runAiAudit({ files, functionalChanges, impacts, pages })
}

console.log(requireAi ? 'Docs impact and AI audit passed.' : 'Docs impact validation passed.')

async function runAiAudit({ files, functionalChanges, impacts, pages }) {
  const provider = (process.env.BEPLY_DOCS_AI_PROVIDER || 'openai').toLowerCase()
  const apiKey = process.env.BEPLY_DOCS_AI_API_KEY || process.env.OPENAI_API_KEY || ''
  const model = process.env.BEPLY_DOCS_AI_MODEL || ''

  if (!apiKey) {
    console.error('ERROR: BEPLY_DOCS_AI_API_KEY is required for --require-ai')
    process.exit(1)
  }
  if (!model) {
    console.error('ERROR: BEPLY_DOCS_AI_MODEL is required for --require-ai')
    process.exit(1)
  }
  if (provider !== 'openai') {
    console.error(`ERROR: Unsupported BEPLY_DOCS_AI_PROVIDER=${provider}. Supported: openai`)
    process.exit(1)
  }

  const publishedSnapshots = []
  for (const page of pages) {
    for (const key of ['publishedUrl', 'baseUrl']) {
      if (!page[key]) {
        continue
      }
      publishedSnapshots.push({
        id: page.id,
        url: page[key],
        content: await fetchPublishedPage(page[key]),
      })
    }
  }

  const prompt = [
    'You are auditing Spanish user documentation for a FacturaScripts plugin release.',
    'Return only JSON with shape {"passed": boolean, "findings": string[]}.',
    'Fail if functional changes are not documented in plugin docs, base docs impact map, and published docs snapshots.',
    '',
    `Changed files: ${JSON.stringify(files)}`,
    `Functional changes: ${JSON.stringify(functionalChanges)}`,
    `Impact map: ${JSON.stringify(impacts)}`,
    `Published pages: ${JSON.stringify(pages)}`,
    `Published docs snapshots: ${JSON.stringify(publishedSnapshots)}`,
    '',
    'Plugin docs:',
    readFileIfExists('docs/user/modulo.md'),
    '',
    'UI coverage:',
    readFileIfExists('docs/testing/ui-coverage-matrix.json'),
  ].join('\n')

  const response = await fetch('https://api.openai.com/v1/responses', {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${apiKey}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      model,
      input: prompt,
    }),
  })

  if (!response.ok) {
    console.error(`ERROR: AI docs audit request failed: ${response.status} ${await response.text()}`)
    process.exit(1)
  }

  const payload = await response.json()
  const text = payload.output_text || extractResponseText(payload)
  const parsed = parseJsonObject(text)
  if (!parsed || parsed.passed !== true) {
    console.error(`ERROR: AI docs audit failed: ${text}`)
    process.exit(1)
  }
}

async function fetchPublishedPage(url) {
  const response = await fetch(url, {
    headers: {
      Accept: 'text/html,application/json,text/plain;q=0.9,*/*;q=0.8',
      'User-Agent': 'beply-plugin-docs-audit/1.0',
    },
  })

  if (!response.ok) {
    console.error(`ERROR: Published docs URL failed: ${url} HTTP ${response.status}`)
    process.exit(1)
  }

  const text = await response.text()
  return text.replace(/\s+/g, ' ').slice(0, 12000)
}

function readFileIfExists(path) {
  const absolute = resolve(root, path)
  return existsSync(absolute) ? readFileSync(absolute, 'utf8') : ''
}

function extractResponseText(payload) {
  const parts = []
  for (const item of payload.output || []) {
    for (const content of item.content || []) {
      if (content.text) {
        parts.push(content.text)
      }
    }
  }
  return parts.join('\n')
}

function parseJsonObject(text) {
  try {
    return JSON.parse(text)
  } catch {
    const match = text.match(/\{[\s\S]*\}/)
    return match ? JSON.parse(match[0]) : null
  }
}
