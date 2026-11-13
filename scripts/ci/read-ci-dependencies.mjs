#!/usr/bin/env node
// Lee .beply/ci-dependencies.json (del plugin; la plantilla nunca lo crea ni lo pisa) y emite las
// salidas que tests.yml usa para clonar otros plugins de Beply en Unit, Runtime y E2E.
// Solo se nombra el secreto de la clave de lectura; su valor lo pone GitHub en el checkout y
// nunca pasa por aquí. Sin fichero o con la lista vacía, las salidas son las de siempre.
import { existsSync, readFileSync } from 'node:fs'

const FILE = '.beply/ci-dependencies.json'
const SLOTS = 4
const FOLDER = /^[A-Za-z][A-Za-z0-9_]{0,63}$/
const REPOSITORY = /^beply-es\/[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$/
const REF = /^[0-9a-f]{40}$/
const SECRET = /^BEPLY_[A-Z0-9]+(?:_[A-Z0-9]+)*_READ_KEY$/
const TOP_KEYS = new Set(['schema', 'plugins'])
const PLUGIN_KEYS = new Set(['repository', 'ref', 'folder', 'sshKeySecret'])

function readDependencies(pluginFolder) {
  if (!existsSync(FILE)) return []
  let data
  try {
    data = JSON.parse(readFileSync(FILE, 'utf8'))
  } catch (error) {
    throw new Error(`${FILE}: JSON inválido (${error.message})`)
  }
  if (data === null || typeof data !== 'object' || Array.isArray(data)) throw new Error(`${FILE}: debe ser un objeto`)
  for (const key of Object.keys(data)) if (!TOP_KEYS.has(key)) throw new Error(`${FILE}: clave desconocida ${key}`)
  if (data.schema !== 1) throw new Error(`${FILE}: schema debe ser 1`)
  if (!Array.isArray(data.plugins)) throw new Error(`${FILE}: plugins debe ser un array`)
  if (data.plugins.length > SLOTS) throw new Error(`${FILE}: como mucho ${SLOTS} dependencias`)

  const folders = new Set()
  const repositories = new Set()
  return data.plugins.map((item, index) => {
    const where = `${FILE}: plugins[${index}]`
    if (item === null || typeof item !== 'object' || Array.isArray(item)) throw new Error(`${where} debe ser un objeto`)
    for (const key of Object.keys(item)) if (!PLUGIN_KEYS.has(key)) throw new Error(`${where}: clave desconocida ${key}`)
    const { repository, ref, folder, sshKeySecret } = item
    if (typeof repository !== 'string' || !REPOSITORY.test(repository) || repository.includes('..')) {
      throw new Error(`${where}: repository debe ser beply-es/<repo>`)
    }
    if (typeof ref !== 'string' || !REF.test(ref)) throw new Error(`${where}: ref debe ser un commit de 40 hex en minúsculas`)
    if (typeof folder !== 'string' || !FOLDER.test(folder)) throw new Error(`${where}: folder debe ser un nombre de carpeta simple`)
    if (typeof sshKeySecret !== 'string' || !SECRET.test(sshKeySecret)) {
      throw new Error(`${where}: sshKeySecret debe ser el nombre de una clave de lectura BEPLY_<REPO>_READ_KEY`)
    }
    if (folder === pluginFolder || repository === `beply-es/${pluginFolder}`) {
      throw new Error(`${where}: no puede ser el propio plugin`)
    }
    if (folders.has(folder)) throw new Error(`${where}: folder repetida ${folder}`)
    if (repositories.has(repository)) throw new Error(`${where}: repository repetido ${repository}`)
    folders.add(folder)
    repositories.add(repository)
    return { repository, ref, folder, sshKeySecret }
  })
}

try {
  const pluginFolder = process.env.PLUGIN_FOLDER || ''
  if (!FOLDER.test(pluginFolder)) throw new Error('PLUGIN_FOLDER ausente o inválido')
  const dependencies = readDependencies(pluginFolder)
  const lines = [
    `has_dependencies=${dependencies.length > 0}`,
    `plugin_folders=${[pluginFolder, ...dependencies.map((item) => item.folder)].join(',')}`,
    `dependency_folders=${dependencies.map((item) => item.folder).join(',')}`,
  ]
  for (let slot = 0; slot < SLOTS; slot++) {
    const item = dependencies[slot] || { repository: '', ref: '', folder: '', sshKeySecret: '' }
    const n = slot + 1
    lines.push(`dep${n}_repository=${item.repository}`, `dep${n}_ref=${item.ref}`, `dep${n}_folder=${item.folder}`, `dep${n}_ssh_key_secret=${item.sshKeySecret}`)
  }
  process.stdout.write(lines.join('\n') + '\n')
} catch (error) {
  console.error(`ERROR: ${error.message}`)
  process.exitCode = 1
}
