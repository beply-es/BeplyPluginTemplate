#!/usr/bin/env node
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const root = process.cwd()
const errors = []

function check(condition, message) {
  if (!condition) {
    errors.push(message)
  }
}

const tests = readFileSync(resolve(root, '.github/workflows/tests.yml'), 'utf8')
const release = readFileSync(resolve(root, '.github/workflows/release.yml'), 'utf8')

check(tests.includes('validate-template-contract.mjs'), 'Tests workflow must run validate-template-contract.mjs')
check(tests.includes('validate-docs-impact.mjs'), 'Tests workflow must run validate-docs-impact.mjs')
check(tests.includes('v2026.3'), 'Tests workflow must include FacturaScripts v2026.3')
check(tests.includes('v2026.2'), 'Tests workflow must include FacturaScripts v2026.2')
check(!/has_tests=false/.test(tests), 'Tests workflow must not silently skip required suites')

check(release.includes('Verify Tests Workflow'), 'Release workflow must wait for Tests')
check(release.includes('validate-docs-impact.mjs --require-ai'), 'Release workflow must require AI docs audit on tags')
check(!/paths-ignore:/.test(release), 'Release workflow must not ignore docs paths')
check(!/GITHUB_SHA::/.test(release), 'Release workflow must not truncate sourceReleaseTag SHA')
check(release.includes('/api/v1/plugins/release'), 'Release workflow must upload through the plugin release API')

if (errors.length > 0) {
  for (const error of errors) {
    console.error(`ERROR: ${error}`)
  }
  process.exit(1)
}

console.log('Release workflow model validation passed.')
