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
  assert.equal(result.status, 1); assert.match(result.stderr, /must not define facturascripts-ref anywhere else/)
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

function demo(dir) {
  const ini = join(dir, 'facturascripts.ini')
  writeFileSync(ini, readFileSync(ini, 'utf8').replace('name = BeplyPluginTemplate', 'name = BeplyDemo'))
  const manifest = join(dir, 'Tools/manifest.json')
  const data = JSON.parse(readFileSync(manifest, 'utf8'))
  data.plugin.name = 'BeplyDemo'
  writeFileSync(manifest, JSON.stringify(data))
}
function contractCase(name, matrix, message, asDemo = true, missingReader = false) {
  test(name, () => fixture((dir) => {
    if (asDemo) demo(dir)
    json(dir, '.beply/facturascripts-matrix.json', matrix)
    if (missingReader) rmSync(join(dir, 'scripts/ci/read-facturascripts-matrix.mjs'))
    const result = run(dir, 'scripts/ci/validate-template-contract.mjs')
    assert.notEqual(result.status, 0)
    assert.ok(result.stderr.includes(message), result.stderr)
  }, true))
}
const required = (ref) => ({ ref, required: true })
contractCase('C1-a plantilla exige v2026.2', { defaultRef: 'v2026.3', supported: [required('v2026.3'), { ref: 'v2026.2', required: false }] }, 'FacturaScripts matrix must require v2026.2', false)
contractCase('C1-b plantilla exige default v2026.3', { ...template, defaultRef: 'v2026.2' }, 'FacturaScripts defaultRef must be v2026.3 until the matrix is intentionally updated', false)
contractCase('C1-c patrón de ref', { defaultRef: 'main', supported: [required('main')] }, 'FacturaScripts required refs must use vYYYY.N format')
contractCase('C1-d duplicados', { defaultRef: 'v2025.71', supported: [required('v2025.71'), required('v2025.71')] }, 'FacturaScripts required refs must be unique')
contractCase('C1-e default opcional', { defaultRef: 'v2026.65', supported: [required('v2025.71'), { ref: 'v2026.65', required: false }] }, 'FacturaScripts defaultRef must be required')
contractCase('C1-f sin requeridos', { defaultRef: 'v2026.65', supported: [{ ref: 'v2026.65', required: false }] }, 'FacturaScripts matrix must require at least one ref')
contractCase('C1-g lector obligatorio', other, 'Missing required file: scripts/ci/read-facturascripts-matrix.mjs', true, true)

function releaseCase(name, edit, expected, message) {
  test(name, () => fixture((dir) => {
    const path = join(dir, '.github/workflows/tests.yml')
    const original = readFileSync(path, 'utf8')
    writeFileSync(path, edit(original))
    const result = run(dir, 'scripts/ci/validate-release-model.mjs')
    assert.equal(result.status, expected, result.stderr)
    if (message) assert.ok(result.stderr.includes(message), result.stderr)
  }, true))
}
const refLine = 'facturascripts-ref: ${{ fromJSON(needs.quality_contract.outputs.fs_refs) }}'
releaseCase('C2-a rechaza lista en bloque', (text) => text.replace(refLine, 'facturascripts-ref:\n          - v2026.3'), 1, 'Tests workflow must define exactly four facturascripts-ref matrices taken from the matrix file')
releaseCase('C2-b rechaza ausencia de matriz', (text) => text.split('\n').filter((line) => !/^\s*facturascripts-ref:/.test(line)).join('\n'), 1, 'Tests workflow must define exactly four facturascripts-ref matrices taken from the matrix file')
releaseCase('C2-c acepta workflow intacto', (text) => text, 0)

releaseCase('C2-d rechaza ref bajo include', (text) => text + '\ninclude:\n  - facturascripts-ref: v2025.1\n', 1)
releaseCase('C2-e rechaza matriz inline', (text) => text + '\nmatrix: { facturascripts-ref: [v2026.3] }\n', 1)
releaseCase('C2-f rechaza solo tres matrices', (text) => text.replace(refLine, 'php-version: [8.2]'), 1)
releaseCase('O1-a rechaza clave entre comillas bajo include', (text) => text.replace(`        ${refLine}`, `        ${refLine}\n        include:\n          - "facturascripts-ref": v2025.1`), 1)
releaseCase('O1-b rechaza clave en fromJSON bajo include', (text) => text.replace(`        ${refLine}`, `        ${refLine}\n        include: \${{ fromJSON('[{"facturascripts-ref":"v2025.1"}]') }}`), 1)
