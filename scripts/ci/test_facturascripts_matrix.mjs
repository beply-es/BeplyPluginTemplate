import { test } from 'node:test'
import assert from 'node:assert/strict'
import { cpSync, mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { basename, join, resolve } from 'node:path'
import { spawnSync } from 'node:child_process'

const root = resolve(import.meta.dirname, '../..')
const template = JSON.parse(readFileSync(join(root, '.beply/facturascripts-matrix.json'), 'utf8'))
const other = { defaultRef: 'v2026.65', supported: [{ ref: 'v2025.71', required: true }, { ref: 'v2026.65', required: true }] }
function fixture(fn, copy = false) {
  const dir = mkdtempSync(join(tmpdir(), 'fs-matrix-'))
  try {
    if (copy) cpSync(root, dir, { recursive: true, filter: (path) => basename(path) !== '.git' })
    else mkdirSync(join(dir, '.beply'))
    fn(dir)
  } finally { rmSync(dir, { recursive: true, force: true }) }
}
function json(dir, path, value) { writeFileSync(join(dir, path), JSON.stringify(value)) }
function run(dir, script, args = []) {
  return spawnSync(process.execPath, [join(root, script), ...args], { cwd: dir, encoding: 'utf8', env: { ...process.env, BEPLY_DOCS_AI_API_KEY: '', OPENAI_API_KEY: '', BEPLY_DOCS_AI_MODEL: '' } })
}
function matrixTest(name, matrix, expected) {
  test(name, () => fixture((dir) => {
    json(dir, '.beply/facturascripts-matrix.json', matrix)
    const result = run(dir, 'scripts/ci/read-facturascripts-matrix.mjs')
    assert.equal(result.status, expected === null ? 1 : 0, result.stderr)
    assert.equal(result.stdout, expected === null ? '' : `fs_refs=${JSON.stringify(expected)}\n`)
    if (expected === null) assert.match(result.stderr, /^ERROR: /)
  }))
}
matrixTest('matriz de plantilla', template, ['v2026.3', 'v2026.2'])
matrixTest('cores propios conservan el orden', other, ['v2025.71', 'v2026.65'])
matrixTest('excluye entradas opcionales', { ...other, supported: [...other.supported, { ref: 'v2024.1', required: false }] }, ['v2025.71', 'v2026.65'])
matrixTest('rechaza ausencia de requeridos', { ...other, supported: [{ ref: 'v2025.71', required: false }] }, null)
matrixTest('rechaza ref inseguro', { defaultRef: 'main; echo x', supported: [{ ref: 'main; echo x', required: true }] }, null)
matrixTest('rechaza default ajeno', { ...other, defaultRef: 'v2020.1' }, null)
matrixTest('rechaza duplicados', { ...other, supported: [...other.supported, other.supported[0]] }, null)
matrixTest('rechaza supported no array', { ...other, supported: {} }, null)
test('rechaza archivo ausente y JSON inválido', () => fixture((dir) => {
  let result = run(dir, 'scripts/ci/read-facturascripts-matrix.mjs')
  assert.equal(result.status, 1); assert.equal(result.stdout, ''); assert.match(result.stderr, /^ERROR: /)
  writeFileSync(join(dir, '.beply/facturascripts-matrix.json'), '{')
  result = run(dir, 'scripts/ci/read-facturascripts-matrix.mjs')
  assert.equal(result.status, 1); assert.equal(result.stdout, ''); assert.match(result.stderr, /^ERROR: /)
}))
test('validador permite cores de plugin y protege los de plantilla', () => fixture((dir) => {
  json(dir, '.beply/facturascripts-matrix.json', other)
  const ini = join(dir, 'facturascripts.ini')
  const original = readFileSync(ini, 'utf8')
  writeFileSync(ini, original.replace('name = BeplyPluginTemplate', 'name = BeplyDemo'))
  const manifest = join(dir, 'Tools/manifest.json')
  const data = JSON.parse(readFileSync(manifest, 'utf8')); data.plugin.name = 'BeplyDemo'; writeFileSync(manifest, JSON.stringify(data))
  let result = run(dir, 'scripts/ci/validate-template-contract.mjs')
  assert.equal(result.status, 0, result.stderr)
  writeFileSync(ini, original); data.plugin.name = 'BeplyPluginTemplate'; writeFileSync(manifest, JSON.stringify(data))
  result = run(dir, 'scripts/ci/validate-template-contract.mjs')
  assert.equal(result.status, 1); assert.match(result.stderr, /FacturaScripts/)
}, true))
test('modelo de release rechaza matriz fija', () => fixture((dir) => {
  const path = join(dir, '.github/workflows/tests.yml')
  writeFileSync(path, readFileSync(path, 'utf8') + "\nfacturascripts-ref: ['v2026.3', 'v2026.2']\n")
  const result = run(dir, 'scripts/ci/validate-release-model.mjs')
  assert.equal(result.status, 1); assert.match(result.stderr, /must not hard-code FacturaScripts refs/)
}, true))
test('impacto en preparación solo exige URL para release', () => fixture((dir) => {
  const path = join(dir, 'docs/docs-sync/impact-map.json')
  const data = JSON.parse(readFileSync(path, 'utf8')); data.impacts[0].status = 'in_preparation'; writeFileSync(path, JSON.stringify(data))
  json(dir, 'docs/docs-sync/published-pages.json', { pages: [] })
  let result = run(dir, 'scripts/ci/validate-docs-impact.mjs')
  assert.equal(result.status, 0, result.stderr); assert.doesNotMatch(result.stderr, /has no published page URL/)
  result = run(dir, 'scripts/ci/validate-docs-impact.mjs', ['--require-ai'])
  assert.equal(result.status, 1); assert.match(result.stderr, /has no published page URL/)
}, true))
