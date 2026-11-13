import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { spawnSync } from 'node:child_process'

const script = resolve(import.meta.dirname, 'read-ci-dependencies.mjs')
const SHA_A = 'a'.repeat(40)
const SHA_B = '0123456789abcdef0123456789abcdef01234567'

// Lo que el workflow recibe hoy, sin lista: solo el plugin y cuatro huecos vacíos.
// Si esto cambia, la CI de los plugins sin dependencias deja de ser la de siempre.
const NO_DEPENDENCIES = [
  'has_dependencies=false',
  'plugin_folders=BeplyDemo',
  'dependency_folders=',
  ...[1, 2, 3, 4].flatMap((n) => [
    `dep${n}_repository=`, `dep${n}_ref=`, `dep${n}_folder=`, `dep${n}_ssh_key_secret=`,
  ]),
].join('\n') + '\n'

function run(content, { plugin = 'BeplyDemo' } = {}) {
  const dir = mkdtempSync(join(tmpdir(), 'ci-deps-'))
  try {
    if (content !== undefined) {
      mkdirSync(join(dir, '.beply'), { recursive: true })
      writeFileSync(join(dir, '.beply/ci-dependencies.json'), typeof content === 'string' ? content : JSON.stringify(content))
    }
    const env = { ...process.env }
    delete env.PLUGIN_FOLDER
    if (plugin !== null) env.PLUGIN_FOLDER = plugin
    return spawnSync(process.execPath, [script], { cwd: dir, env, encoding: 'utf8' })
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
}

const dep = (overrides = {}) => ({
  repository: 'beply-es/BeplyProyectos',
  ref: SHA_A,
  folder: 'BeplyProyectos',
  sshKeySecret: 'BEPLY_PROYECTOS_READ_KEY',
  ...overrides,
})

function rejects(content, pattern, options) {
  const result = run(content, options)
  assert.notEqual(result.status, 0, `debía fallar: ${JSON.stringify(content)}`)
  assert.equal(result.stdout, '', 'un fallo no emite salidas a medias')
  assert.match(result.stderr, pattern)
}

test('sin fichero, las salidas son exactamente las de hoy', () => {
  const result = run(undefined)
  assert.equal(result.status, 0, result.stderr)
  assert.equal(result.stdout, NO_DEPENDENCIES)
})

test('con lista vacía, las mismas salidas que sin fichero', () => {
  const result = run({ schema: 1, plugins: [] })
  assert.equal(result.status, 0, result.stderr)
  assert.equal(result.stdout, NO_DEPENDENCIES)
})

test('con dependencias, emite cada hueco y la lista de carpetas en orden', () => {
  const result = run({
    schema: 1,
    plugins: [
      dep(),
      dep({ repository: 'beply-es/BeplyStockAvanzado', ref: SHA_B, folder: 'StockAvanzado', sshKeySecret: 'BEPLY_STOCK_AVANZADO_READ_KEY' }),
    ],
  })
  assert.equal(result.status, 0, result.stderr)
  assert.equal(result.stdout, [
    'has_dependencies=true',
    'plugin_folders=BeplyDemo,BeplyProyectos,StockAvanzado',
    'dependency_folders=BeplyProyectos,StockAvanzado',
    'dep1_repository=beply-es/BeplyProyectos', `dep1_ref=${SHA_A}`, 'dep1_folder=BeplyProyectos', 'dep1_ssh_key_secret=BEPLY_PROYECTOS_READ_KEY',
    'dep2_repository=beply-es/BeplyStockAvanzado', `dep2_ref=${SHA_B}`, 'dep2_folder=StockAvanzado', 'dep2_ssh_key_secret=BEPLY_STOCK_AVANZADO_READ_KEY',
    ...[3, 4].flatMap((n) => [`dep${n}_repository=`, `dep${n}_ref=`, `dep${n}_folder=`, `dep${n}_ssh_key_secret=`]),
  ].join('\n') + '\n')
})

test('la clave solo se nombra: el valor nunca sale del lector', () => {
  const result = run({ schema: 1, plugins: [dep()] })
  assert.equal(result.status, 0, result.stderr)
  assert.doesNotMatch(result.stdout, /BEGIN|PRIVATE|ssh-(rsa|ed25519)/)
})

test('PLUGIN_FOLDER es obligatorio y con forma de carpeta', () => {
  rejects(undefined, /PLUGIN_FOLDER/, { plugin: null })
  rejects(undefined, /PLUGIN_FOLDER/, { plugin: '../x' })
})

test('JSON inválido, esquema o claves desconocidas se rechazan', () => {
  rejects('{', /JSON/)
  rejects({ schema: 2, plugins: [] }, /schema/)
  rejects({ plugins: [] }, /schema/)
  rejects({ schema: 1 }, /plugins/)
  rejects({ schema: 1, plugins: {} }, /plugins/)
  rejects({ schema: 1, plugins: [], extra: true }, /extra/)
  rejects({ schema: 1, plugins: [{ ...dep(), token: 'x' }] }, /token/)
  rejects({ schema: 1, plugins: [null] }, /objeto/)
})

test('solo repositorios de beply-es', () => {
  rejects({ schema: 1, plugins: [dep({ repository: 'NeoRazorX/facturascripts' })] }, /repository/)
  rejects({ schema: 1, plugins: [dep({ repository: 'beply-es/../otro' })] }, /repository/)
  rejects({ schema: 1, plugins: [dep({ repository: 'beply-es/A\nB' })] }, /repository/)
  rejects({ schema: 1, plugins: [dep({ repository: 'beply-es/BeplyDemo' })] }, /propio plugin/)
})

test('la referencia es un commit exacto de 40 hex, nunca una rama ni un tag', () => {
  for (const ref of ['main', 'v1.2', SHA_A.slice(0, 39), SHA_A.toUpperCase(), `${SHA_A}\n`, '']) {
    rejects({ schema: 1, plugins: [dep({ ref })] }, /ref/)
  }
})

test('el secreto es una clave de lectura BEPLY_*_READ_KEY, nunca otro secreto', () => {
  for (const sshKeySecret of ['GITHUB_TOKEN', 'CODECOV_TOKEN', 'BEPLY_PROYECTOS_KEY', 'beply_x_read_key', 'BEPLY__READ_KEY', 'BEPLY_X_READ_KEY\nX', '']) {
    rejects({ schema: 1, plugins: [dep({ sshKeySecret })] }, /sshKeySecret/)
  }
})

test('la carpeta es un nombre simple, distinto del plugin y sin repetir', () => {
  for (const folder of ['../BeplyCore', 'a/b', '.hidden', '', 'x'.repeat(65), 'Bad-Name']) {
    rejects({ schema: 1, plugins: [dep({ folder })] }, /folder/)
  }
  rejects({ schema: 1, plugins: [dep({ folder: 'BeplyDemo' })] }, /propio plugin/)
  rejects({ schema: 1, plugins: [dep(), dep({ repository: 'beply-es/Otro', sshKeySecret: 'BEPLY_OTRO_READ_KEY' })] }, /folder repetida/)
  rejects({ schema: 1, plugins: [dep(), dep({ folder: 'Otro' })] }, /repository repetido/)
})

test('como mucho cuatro dependencias, los huecos del workflow', () => {
  const plugins = [1, 2, 3, 4, 5].map((n) => dep({ repository: `beply-es/P${n}`, folder: `P${n}`, sshKeySecret: `BEPLY_P${n}_READ_KEY` }))
  rejects({ schema: 1, plugins }, /4/)
  const result = run({ schema: 1, plugins: plugins.slice(0, 4) })
  assert.equal(result.status, 0, result.stderr)
  assert.match(result.stdout, /^dep4_folder=P4$/m)
})
