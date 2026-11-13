import { test } from 'node:test'
import assert from 'node:assert/strict'
import { cpSync, mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { spawnSync } from 'node:child_process'

const root = resolve(import.meta.dirname, '../..')
function populate(dir) {
  const files = [
    'AGENTS.md', 'README.md', 'Tools/README.md', 'docs/CODEX-WORKFLOW.md', 'docs/TESTING.md',
    'docs/FACTURASCRIPTS-STYLE-GUIDE.md', 'docs/DOCUMENTATION-GOVERNANCE.md',
    'docs/AI-TOOLS-MANIFEST.md', 'docs/ROM-COPY-CLEANROOM.md', 'docs/TEMPLATE-SYNC.md',
    'docs/CI-CD.md', 'docs/user/modulo.md', 'tests/e2e/smoke.spec.ts',
    'phpunit.unit.xml.dist', 'phpunit.runtime.xml.dist', 'scripts/ci/build_plugin_zip.py',
    'scripts/ci/build_plugin_artifact_attestation.mjs', 'scripts/ci/immutable_plugin_contract.py',
    'scripts/ci/test_immutable_plugin_contract.py', 'scripts/template/sync-template.mjs',
    'Lib/BeplyAgentToolProvider.php', 'Lib/TemplateToolsManifest.php',
  ]
  function put(path, text = '') {
    const target = join(dir, path)
    mkdirSync(dirname(target), { recursive: true })
    writeFileSync(target, text)
  }
  for (const file of files) put(file)
  for (const script of ['read-facturascripts-matrix.mjs', 'validate-template-contract.mjs', 'validate-release-model.mjs', 'validate-docs-impact.mjs']) {
    const target = `scripts/ci/${script}`
    mkdirSync(dirname(join(dir, target)), { recursive: true })
    cpSync(join(root, target), join(dir, target))
  }
  const data = (path, value) => put(path, JSON.stringify(value))
  put('facturascripts.ini', 'name = BeplyPluginTemplate\nversion = 1.5\nmin_php = 8.2\n')
  data('.beply/facturascripts-matrix.json', { defaultRef: 'v2026.3', supported: [{ ref: 'v2026.3', required: true }, { ref: 'v2026.2', required: true }] })
  data('.beply/template-lock.json', { template: 'beply-es/BeplyPluginTemplate', version: '1.5', ref: 'v1.5' })
  data('.beply/template-sync.json', { defaultRef: 'v1.5', overwrite: [], createIfMissing: ['.github/workflows/release.yml', '.github/workflows/promote-prod.yml'], neverOverwrite: ['Init.php', 'Tools/manifest.json', 'docs/user/', 'docs/docs-sync/impact-map.json', 'docs/testing/ui-coverage-matrix.json'] })
  data('Tools/manifest.json', { schemaVersion: 'beply.facturascripts-plugin-tools.v1', plugin: { name: 'BeplyPluginTemplate' }, executionPolicy: { humanReviewRequired: true }, tools: [], toolPacks: [], runtimeTools: [] })
  data('docs/docs-sync/impact-map.json', { impacts: [{ id: 'demo', basePage: { path: 'base.md' }, pluginPage: { path: 'docs/user/modulo.md' }, surfaces: ['demo'], changes: { actions: [], flows: [] }, tests: ['demo'] }] })
  data('docs/docs-sync/published-pages.json', { pages: [{ id: 'demo', publishedUrl: 'https://example.invalid/demo' }] })
  data('docs/testing/ui-coverage-matrix.json', { surfaces: [] })
  put('CHANGELOG.md', '## v1.5 - 2026-01-01\n')
  const ref = 'facturascripts-ref: ${{ fromJSON(needs.quality_contract.outputs.fs_refs) }}'
  put('.github/workflows/tests.yml', ['validate-template-contract.mjs', 'validate-docs-impact.mjs', 'read-facturascripts-matrix.mjs', ...Array(4).fill(`        ${ref}`)].join('\n') + '\n')
  put('.github/workflows/release.yml', 'Verify Tests Workflow\nvalidate-docs-impact.mjs --require-ai\nuses: ./.github/workflows/reusable-immutable-plugin-candidate.yml\n')
  put('.github/workflows/promote-prod.yml', 'uses: ./.github/workflows/reusable-promote-immutable-plugin-candidate.yml\n')
  put('.github/workflows/reusable-immutable-plugin-candidate.yml', [
    'workflow_call:', 'scripts/ci/build_plugin_zip.py', 'gh release download', '--repo "${GITHUB_REPOSITORY}"', 'pending_review',
    'build_source_provenance_manifest.mjs', `uses: actions/upload-artifact@${'a'.repeat(40)}`,
    'name: plugin-source-provenance-${{ github.run_id }}-${{ github.run_attempt }}', 'needs: source_provenance', 'sourceProvenance=${SOURCE_PROVENANCE_LOCATOR}',
  ].join('\n'))
  put('.github/workflows/reusable-promote-immutable-plugin-candidate.yml', [
    'workflow_call:', 'gh release download', '--repo "${SOURCE_REPO_FULL_NAME}"', 'inputs.source_repo_full_name || github.repository',
    'immutable_plugin_contract.py', 'dev_validation_run_id', 'dev_validation_head_sha', 'expected_checksum', 'expected_file_size', 'dev_candidate_version_id', 'pending_review',
  ].join('\n'))
}
function fixture(fn) {
  const dir = mkdtempSync(join(tmpdir(), 'tools-contract-'))
  try {
    populate(dir)
    fn(dir)
  } finally { rmSync(dir, { recursive: true, force: true }) }
}
function run(dir) {
  return spawnSync(process.execPath, ['scripts/ci/validate-template-contract.mjs'], { cwd: dir, encoding: 'utf8' })
}
function demo(dir, field) {
  const ini = join(dir, 'facturascripts.ini')
  writeFileSync(ini, readFileSync(ini, 'utf8').replace('name = BeplyPluginTemplate', 'name = BeplyDemo'))
  const manifest = join(dir, 'Tools/manifest.json')
  const data = JSON.parse(readFileSync(manifest, 'utf8'))
  data.plugin.name = 'BeplyDemo'
  data.tools = []; data.toolPacks = []; data.runtimeTools = []
  if (field) data[field] = [field === 'runtimeTools' ? { name: 'demo_tool', toolType: 'read', parameters: { additionalProperties: false } } : { name: 'demo_tool' }]
  writeFileSync(manifest, JSON.stringify(data))
  rmSync(join(dir, 'Lib/BeplyAgentToolProvider.php'))
  rmSync(join(dir, 'Lib/TemplateToolsManifest.php'))
}
test('plantilla intacta valida', () => fixture((dir) => {
  const result = run(dir)
  assert.equal(result.status, 0, result.stderr)
  const manifest = join(dir, 'Tools/manifest.json')
  const data = JSON.parse(readFileSync(manifest, 'utf8'))
  data.plugin.name = 'OtroPlugin'
  writeFileSync(manifest, JSON.stringify(data))
  const mismatch = run(dir)
  assert.notEqual(mismatch.status, 0)
  assert.match(mismatch.stderr, /plugin.name must match facturascripts.ini/)
}))
test('plugin sin tools no necesita proveedor ni manifiesto de plantilla', () => fixture((dir) => {
  demo(dir)
  const result = run(dir)
  const output = result.stdout + result.stderr
  assert.doesNotMatch(output, /Lib\/BeplyAgentToolProvider\.php|Lib\/TemplateToolsManifest\.php/)
}))
for (const field of ['tools', 'toolPacks', 'runtimeTools']) {
  test(`plugin con ${field} exige proveedor`, () => fixture((dir) => {
    demo(dir, field)
    const result = run(dir)
    const output = result.stdout + result.stderr
    assert.notEqual(result.status, 0)
    assert.match(output, /Lib\/BeplyAgentToolProvider\.php/)
    assert.doesNotMatch(output, /Lib\/TemplateToolsManifest\.php/)
  }))
}
test('plantilla exige su manifiesto PHP', () => fixture((dir) => {
  rmSync(join(dir, 'Lib/TemplateToolsManifest.php'))
  const result = run(dir)
  assert.notEqual(result.status, 0)
  assert.match(result.stdout + result.stderr, /Lib\/TemplateToolsManifest\.php/)
}))

for (const key of ['tools', 'toolPacks', 'runtimeTools']) {
  test(`C1: ${key} como objeto no vacío exige proveedor y array`, () => fixture((dir) => {
    demo(dir)
    const path = join(dir, 'Tools/manifest.json')
    const data = JSON.parse(readFileSync(path, 'utf8'))
    data[key] = { demo: { id: 'demo', name: 'demo_tool' } }
    writeFileSync(path, JSON.stringify(data))
    const result = run(dir)
    const output = result.stdout + result.stderr
    assert.notEqual(result.status, 0)
    assert.ok(output.includes('Lib/BeplyAgentToolProvider.php'), output)
    assert.ok(output.includes(`${key} must be an array`), output)
    assert.doesNotMatch(output, /TypeError/)
  }))
}
test('C1: objeto vacío es inválido pero no declara tools', () => fixture((dir) => {
  demo(dir)
  const path = join(dir, 'Tools/manifest.json')
  const data = JSON.parse(readFileSync(path, 'utf8'))
  data.tools = null; data.toolPacks = {}
  writeFileSync(path, JSON.stringify(data))
  const result = run(dir)
  const output = result.stdout + result.stderr
  assert.notEqual(result.status, 0)
  assert.doesNotMatch(output, /Lib\/BeplyAgentToolProvider\.php/)
  assert.match(output, /toolPacks must be an array/)
}))
test('C2: plantilla exige proveedor incluso sin tools', () => fixture((dir) => {
  rmSync(join(dir, 'Lib/BeplyAgentToolProvider.php'))
  const result = run(dir)
  assert.notEqual(result.status, 0)
  assert.match(result.stdout + result.stderr, /Lib\/BeplyAgentToolProvider\.php/)
}))
