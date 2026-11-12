#!/usr/bin/env node
import { readFileSync } from 'node:fs'

try {
  const matrix = JSON.parse(readFileSync('.beply/facturascripts-matrix.json', 'utf8'))
  if (!Array.isArray(matrix?.supported)) throw new Error('supported debe ser un array')
  const refs = matrix.supported.filter((item) => item?.required === true).map((item) => item.ref)
  if (refs.length === 0) throw new Error('se requiere al menos un core')
  if (refs.some((ref) => typeof ref !== 'string' || !/^v\d{4}\.\d{1,3}$/.test(ref))) throw new Error('ref requerido inválido')
  if (new Set(refs).size !== refs.length) throw new Error('ref requerido duplicado')
  if (!refs.includes(matrix.defaultRef)) throw new Error('defaultRef debe estar entre los requeridos')
  console.log(`fs_refs=${JSON.stringify(refs)}`)
} catch (error) {
  console.error(`ERROR: ${error.message}`)
  process.exitCode = 1
}
