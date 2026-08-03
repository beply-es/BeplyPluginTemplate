#!/usr/bin/env node
import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const root = process.cwd()
const errors = []

function fail(message) {
  errors.push(message)
}

function requireFile(path) {
  if (!existsSync(resolve(root, path))) {
    fail(`Missing required file: ${path}`)
  }
}

function readJson(path) {
  requireFile(path)
  try {
    return JSON.parse(readFileSync(resolve(root, path), 'utf8'))
  } catch (error) {
    fail(`Invalid JSON in ${path}: ${error.message}`)
    return {}
  }
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

for (const path of [
  'AGENTS.md',
  'README.md',
  'facturascripts.ini',
  '.beply/facturascripts-matrix.json',
  '.beply/template-lock.json',
  '.beply/template-sync.json',
  'Tools/manifest.json',
  'Tools/README.md',
  'Lib/BeplyAgentToolProvider.php',
  'Lib/TemplateToolsManifest.php',
  'docs/CODEX-WORKFLOW.md',
  'docs/TESTING.md',
  'docs/FACTURASCRIPTS-STYLE-GUIDE.md',
  'docs/DOCUMENTATION-GOVERNANCE.md',
  'docs/AI-TOOLS-MANIFEST.md',
  'docs/ROM-COPY-CLEANROOM.md',
  'docs/TEMPLATE-SYNC.md',
  'docs/CI-CD.md',
  'docs/user/modulo.md',
  'docs/docs-sync/impact-map.json',
  'docs/docs-sync/published-pages.json',
  'docs/testing/ui-coverage-matrix.json',
  'tests/e2e/smoke.spec.ts',
  'phpunit.unit.xml.dist',
  'phpunit.runtime.xml.dist',
  'scripts/ci/build_plugin_zip.py',
  'scripts/ci/build_plugin_artifact_attestation.mjs',
  'scripts/ci/immutable_plugin_contract.py',
  'scripts/ci/test_immutable_plugin_contract.py',
  'scripts/template/sync-template.mjs',
]) {
  requireFile(path)
}

const ini = parseIni('facturascripts.ini')
const isTemplate = ini.name === 'BeplyPluginTemplate'
if (isTemplate) {
  for (const path of [
    '.github/workflows/reusable-immutable-plugin-candidate.yml',
    '.github/workflows/reusable-promote-immutable-plugin-candidate.yml',
    '.github/workflows/promote-prod.yml',
  ]) {
    requireFile(path)
  }
}
if (!/^\d+\.\d+$/.test(ini.version || '')) {
  fail('facturascripts.ini version must use X.Y format')
}
if (ini.min_php !== '8.4') {
  fail('facturascripts.ini min_php must be 8.4')
}

const matrix = readJson('.beply/facturascripts-matrix.json')
const supported = Array.isArray(matrix.supported) ? matrix.supported : []
if (matrix.defaultRef !== 'v2026.3') {
  fail('FacturaScripts defaultRef must be v2026.3 until the matrix is intentionally updated')
}

const templateLock = readJson('.beply/template-lock.json')
if (templateLock.template !== 'beply-es/BeplyPluginTemplate') {
  fail('template-lock template must be beply-es/BeplyPluginTemplate')
}
if (isTemplate && templateLock.version !== ini.version) {
  fail('template-lock version must match facturascripts.ini')
}

const templateSync = readJson('.beply/template-sync.json')
if (!Array.isArray(templateSync.overwrite) || !Array.isArray(templateSync.createIfMissing) || !Array.isArray(templateSync.neverOverwrite)) {
  fail('template-sync must declare overwrite, createIfMissing and neverOverwrite arrays')
}
for (const forbidden of ['Init.php', 'Tools/manifest.json', 'docs/user/', 'docs/docs-sync/impact-map.json', 'docs/testing/ui-coverage-matrix.json']) {
  if (!templateSync.neverOverwrite.includes(forbidden)) {
    fail(`template-sync neverOverwrite must include ${forbidden}`)
  }
}
for (const forbidden of templateSync.neverOverwrite || []) {
  if ((templateSync.overwrite || []).includes(forbidden)) {
    fail(`template-sync cannot overwrite protected path ${forbidden}`)
  }
}
for (const adapter of ['.github/workflows/release.yml', '.github/workflows/promote-prod.yml']) {
  if ((templateSync.overwrite || []).includes(adapter)) {
    fail(`template-sync must not overwrite product release adapter ${adapter}`)
  }
  if (!(templateSync.createIfMissing || []).includes(adapter)) {
    fail(`template-sync must create missing release adapter ${adapter}`)
  }
}
for (const ref of ['v2026.3', 'v2026.2']) {
  if (!supported.some((item) => item.ref === ref && item.required === true)) {
    fail(`FacturaScripts matrix must require ${ref}`)
  }
}

const toolsManifest = readJson('Tools/manifest.json')
if (toolsManifest.schemaVersion !== 'beply.facturascripts-plugin-tools.v1') {
  fail('Tools/manifest.json schemaVersion is invalid')
}
if (toolsManifest.plugin?.name !== ini.name) {
  fail('Tools/manifest.json plugin.name must match facturascripts.ini')
}
if (toolsManifest.executionPolicy?.humanReviewRequired !== true) {
  fail('Tools execution policy must require human review by default')
}
for (const tool of toolsManifest.runtimeTools || []) {
  if (!tool.name || !tool.toolType || !tool.parameters) {
    fail(`Runtime tool is missing name/toolType/parameters: ${JSON.stringify(tool)}`)
  }
  if (tool.parameters?.additionalProperties !== false) {
    fail(`Runtime tool ${tool.name} must set parameters.additionalProperties=false`)
  }
}

const impactMap = readJson('docs/docs-sync/impact-map.json')
if (!Array.isArray(impactMap.impacts) || impactMap.impacts.length === 0) {
  fail('docs/docs-sync/impact-map.json must contain at least one impact entry')
}
for (const impact of impactMap.impacts || []) {
  if (!impact.id || !impact.basePage?.path || !impact.pluginPage?.path) {
    fail(`Docs impact entry is incomplete: ${JSON.stringify(impact)}`)
  }
  if (impact.pluginPage?.path && !existsSync(resolve(root, impact.pluginPage.path))) {
    fail(`Docs impact plugin page does not exist: ${impact.pluginPage.path}`)
  }
}

const coverage = readJson('docs/testing/ui-coverage-matrix.json')
for (const surface of coverage.surfaces || []) {
  for (const control of surface.controls || []) {
    if (!control.id || !control.label || !control.type) {
      fail(`UI coverage control is incomplete in ${surface.id}`)
    }
    if (!Array.isArray(control.testIds) || control.testIds.length === 0) {
      fail(`UI coverage control ${control.id} has no testIds`)
    }
  }
}

const releaseWorkflow = readFileSync(resolve(root, '.github/workflows/release.yml'), 'utf8')
const testsWorkflow = readFileSync(resolve(root, '.github/workflows/tests.yml'), 'utf8')
if (/paths-ignore:/.test(releaseWorkflow)) {
  fail('Release workflow must not ignore docs/tests paths; docs are part of the release contract')
}
if (isTemplate && !testsWorkflow.includes("vars.BEPLY_GHA_RUNNER || 'ubuntu-24.04'")) {
  fail('Public template CI must retain a GitHub-hosted runner fallback')
}

if (errors.length > 0) {
  for (const error of errors) {
    console.error(`ERROR: ${error}`)
  }
  process.exit(1)
}

console.log('Template contract validation passed.')
