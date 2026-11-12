import { test } from 'node:test'
import assert from 'node:assert/strict'
import { cpSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { basename, join, resolve } from 'node:path'
import { spawnSync } from 'node:child_process'

const root = resolve(import.meta.dirname, '../..')
function fixture(fn) {
  const dir = mkdtempSync(join(tmpdir(), 'tools-contract-'))
  try {
    cpSync(root, dir, { recursive: true, filter: (path) => !['.git', 'node_modules'].includes(basename(path)) })
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
