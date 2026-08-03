#!/usr/bin/env node
import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const root = process.cwd()
const errors = []

function check(condition, message) {
  if (!condition) {
    errors.push(message)
  }
}

function optional(path) {
  const absolute = resolve(root, path)
  return existsSync(absolute) ? readFileSync(absolute, 'utf8') : ''
}

const tests = readFileSync(resolve(root, '.github/workflows/tests.yml'), 'utf8')
const release = readFileSync(resolve(root, '.github/workflows/release.yml'), 'utf8')
const ini = readFileSync(resolve(root, 'facturascripts.ini'), 'utf8')
const candidate = optional('.github/workflows/reusable-immutable-plugin-candidate.yml')
const promotion = optional('.github/workflows/reusable-promote-immutable-plugin-candidate.yml')
const promotionAdapter = optional('.github/workflows/promote-prod.yml')
const isTemplate = /^name\s*=\s*["']?BeplyPluginTemplate["']?\s*$/m.test(ini)

check(tests.includes('validate-template-contract.mjs'), 'Tests workflow must run validate-template-contract.mjs')
check(tests.includes('validate-docs-impact.mjs'), 'Tests workflow must run validate-docs-impact.mjs')
check(tests.includes('v2026.3'), 'Tests workflow must include FacturaScripts v2026.3')
check(tests.includes('v2026.2'), 'Tests workflow must include FacturaScripts v2026.2')
check(!/has_tests=false/.test(tests), 'Tests workflow must not silently skip required suites')

check(release.includes('Verify Tests Workflow'), 'Release workflow must wait for Tests')
check(release.includes('validate-docs-impact.mjs --require-ai'), 'Release workflow must require AI docs audit on tags')
check(!/paths-ignore:/.test(release), 'Release workflow must not ignore docs paths')
check(!/GITHUB_SHA::/.test(release), 'Release workflow must not truncate sourceReleaseTag SHA')

const pinnedCandidateAdapter = /uses:\s*beply-es\/BeplyPluginTemplate\/\.github\/workflows\/reusable-immutable-plugin-candidate\.yml@[0-9a-f]{40}/.test(release)
const pinnedPromotionAdapter = /uses:\s*beply-es\/BeplyPluginTemplate\/\.github\/workflows\/reusable-promote-immutable-plugin-candidate\.yml@[0-9a-f]{40}/.test(promotionAdapter)
const localCandidateAdapter = release.includes('./.github/workflows/reusable-immutable-plugin-candidate.yml')
const localPromotionAdapter = promotionAdapter.includes('./.github/workflows/reusable-promote-immutable-plugin-candidate.yml')

if (isTemplate) {
  check(localCandidateAdapter, 'Template release workflow must call the local immutable candidate contract')
  check(localPromotionAdapter, 'Template PROD adapter must call the local immutable promotion contract')
  check(candidate.length > 0, 'Missing reusable immutable plugin candidate workflow')
  check(promotion.length > 0, 'Missing reusable immutable plugin promotion workflow')
  check(candidate.includes('workflow_call:'), 'Candidate contract must be a reusable workflow')
  check(promotion.includes('workflow_call:'), 'Promotion contract must be a reusable workflow')
  check(candidate.includes('BEPLY_PLUGIN_TEMPLATE_READ_TOKEN'), 'Candidate contract must fail closed on private template checkout')
  check(promotion.includes('BEPLY_PLUGIN_TEMPLATE_READ_TOKEN'), 'Promotion contract must fail closed on private template checkout')
  check(candidate.includes('scripts/ci/build_plugin_zip.py'), 'Candidate contract must use the canonical deterministic ZIP builder')
  check((candidate.match(/build_plugin_zip\.py/g) || []).length === 1, 'Candidate contract must invoke the ZIP builder exactly once')
  check(candidate.includes('gh release download'), 'Candidate contract must reuse an existing immutable release asset on retry')
  check(candidate.includes('--repo "${GITHUB_REPOSITORY}"'), 'Candidate contract must resolve the caller repository explicitly')
  check(candidate.includes('pending_review'), 'Candidate contract must leave the DEV candidate pending review')
  check(!candidate.includes('BEPLY_PROD_CI_TOKEN'), 'Candidate contract must not contain PROD credentials')
  check(promotion.includes('gh release download'), 'Promotion contract must download the immutable release asset')
  check(promotion.includes('--repo "${GITHUB_REPOSITORY}"'), 'Promotion contract must resolve the caller repository explicitly')
  check(!promotion.includes('build_plugin_zip.py'), 'Promotion contract must never rebuild the plugin payload')
  check(promotion.includes('immutable_plugin_contract.py'), 'Promotion contract must verify machine-readable DEV100 evidence')
  check(promotion.includes('dev_validation_run_id'), 'Promotion contract must pin the DEV100 run')
  check(promotion.includes('dev_validation_head_sha'), 'Promotion contract must pin the DEV100 source SHA')
  check(promotion.includes('expected_checksum'), 'Promotion contract must pin the exact SHA-256')
  check(promotion.includes('expected_file_size'), 'Promotion contract must pin the exact byte size')
  check(promotion.includes('dev_candidate_version_id'), 'Promotion contract must pin the exact DEV version UUID')
  check(promotion.includes('pending_review'), 'Promotion contract must leave PROD pending canonical approval')
} else if (pinnedCandidateAdapter || pinnedPromotionAdapter) {
  check(pinnedCandidateAdapter, 'Migrated plugin must pin the candidate contract to an exact template SHA')
  check(pinnedPromotionAdapter, 'Migrated plugin must pin the promotion contract to an exact template SHA')
}

if (localCandidateAdapter || pinnedCandidateAdapter) {
  check(!release.includes('Build plugin zip'), 'Immutable release adapter must not implement packaging')
  check(!release.includes('/api/v1/plugins/release'), 'Immutable release adapter must not implement platform upload')
}
if (localPromotionAdapter || pinnedPromotionAdapter) {
  check(!promotionAdapter.includes('gh release download'), 'Immutable PROD adapter must not implement artifact transport')
  check(!promotionAdapter.includes('/api/v1/plugins/release'), 'Immutable PROD adapter must not implement platform upload')
}

if (errors.length > 0) {
  for (const error of errors) {
    console.error(`ERROR: ${error}`)
  }
  process.exit(1)
}

console.log('Release workflow model validation passed.')
