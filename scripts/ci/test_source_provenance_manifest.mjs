import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import {
  MANIFEST_SCHEMA,
  ProvenanceError,
  buildManifest,
  callerWorkflowPath,
  canonicalJson,
  selectPublisherJob,
  selectReleaseAsset,
  sourceEvent,
  validateManifest,
} from './build_source_provenance_manifest.mjs'

const zipSha256 = `sha256:${'a'.repeat(64)}`
const facts = {
  repository: 'beply-es/BeplyCRM',
  repositoryId: 1228799189,
  commitSha: 'b'.repeat(40),
  releaseTag: 'v16.4',
  workflowPath: '.github/workflows/release.yml',
  workflowBlobSha: 'c'.repeat(40),
  runId: 19000000001,
  runAttempt: 1,
  publisherJobKey: 'publish_immutable_candidate',
  publisherJobId: 54000000001,
  event: 'push',
  ref: 'refs/tags/v16.4',
  release: { id: 250000001, publishedAt: '2026-10-07T12:00:00Z' },
  asset: { id: 300000001, name: 'BeplyCRM-v16.4.zip', sha256: zipSha256, sizeBytes: 4242 },
  pluginName: 'BeplyCRM',
  pluginVersion: '16.4',
}

test('builds the exact strict manifest field set expected by the platform schema', () => {
  const manifest = buildManifest(facts)
  assert.equal(manifest.schema, MANIFEST_SCHEMA)
  assert.deepEqual(Object.keys(manifest).sort(), ['asset', 'plugin', 'release', 'schema', 'source'])
  assert.deepEqual(Object.keys(manifest.source).sort(), [
    'commitSha', 'event', 'publisherJobId', 'publisherJobKey', 'ref', 'releaseTag', 'repository',
    'repositoryId', 'runAttempt', 'runId', 'workflowBlobSha', 'workflowPath',
  ])
  assert.deepEqual(manifest.plugin, { fsName: 'BeplyCRM', version: '16.4' })
})

test('serialises canonical JSON: recursively sorted keys, no whitespace, no trailing newline', () => {
  const bytes = canonicalJson(buildManifest(facts))
  assert.ok(!bytes.endsWith('\n'))
  assert.ok(!/\s/.test(bytes.replace(/"[^"]*"/g, '')))
  assert.ok(bytes.startsWith('{"asset":{"id":300000001,"name":"BeplyCRM-v16.4.zip","sha256":"sha256:'))
  assert.ok(bytes.includes('"source":{"commitSha":"' + 'b'.repeat(40) + '","event":"push"'))
  assert.equal(canonicalJson(JSON.parse(bytes)), bytes)
})

test('matches the golden canonical carrier shared with the platform test fixture', () => {
  const golden = readFileSync(new URL('./fixtures/source-provenance-manifest.golden.json', import.meta.url), 'utf8')
  assert.equal(canonicalJson(buildManifest(facts)), golden)
})

for (const [name, mutate] of [
  ['extra top-level claim', (m) => { m.verified = true }],
  ['extra source claim', (m) => { m.source.protected = true }],
  ['missing source field', (m) => { delete m.source.workflowBlobSha }],
  ['short commit', (m) => { m.source.commitSha = 'b'.repeat(12) }],
  ['uppercase commit', (m) => { m.source.commitSha = 'B'.repeat(40) }],
  ['pull_request event', (m) => { m.source.event = 'pull_request' }],
  ['workflow outside .github/workflows', (m) => { m.source.workflowPath = 'release.yml' }],
  ['string run id', (m) => { m.source.runId = '19000000001' }],
  ['zero attempt', (m) => { m.source.runAttempt = 0 }],
  ['boolean job id', (m) => { m.source.publisherJobId = true }],
  ['digest without prefix', (m) => { m.asset.sha256 = 'a'.repeat(64) }],
  ['non-positive size', (m) => { m.asset.sizeBytes = 0 }],
  ['invalid publication time', (m) => { m.release.publishedAt = '07/10/2026' }],
  ['invalid fsName', (m) => { m.plugin.fsName = 'Beply-CRM' }],
  ['wrong schema', (m) => { m.schema = 'beply-plugin-source-provenance-v2' }],
]) {
  test(`rejects ${name}`, () => {
    const manifest = structuredClone(buildManifest(facts))
    mutate(manifest)
    assert.throws(() => validateManifest(manifest), ProvenanceError)
  })
}

test('derives the caller workflow path only from the caller repository and exact ref', () => {
  assert.equal(
    callerWorkflowPath('beply-es/BeplyCRM/.github/workflows/release.yml@refs/tags/v16.4', 'beply-es/BeplyCRM', 'refs/tags/v16.4'),
    '.github/workflows/release.yml',
  )
  assert.throws(() => callerWorkflowPath(
    'beply-es/BeplyPluginTemplate/.github/workflows/reusable-immutable-plugin-candidate.yml@refs/tags/v16.4',
    'beply-es/BeplyCRM', 'refs/tags/v16.4'), ProvenanceError)
  assert.throws(() => callerWorkflowPath(
    'beply-es/BeplyCRM/.github/workflows/release.yml@refs/heads/main', 'beply-es/BeplyCRM', 'refs/tags/v16.4'), ProvenanceError)
  assert.throws(() => callerWorkflowPath(
    'beply-es/BeplyCRM/../release.yml@refs/tags/v16.4', 'beply-es/BeplyCRM', 'refs/tags/v16.4'), ProvenanceError)
})

const inner = 'Publish Immutable Release And Source Provenance Carrier'
const job = (patch) => ({
  id: 54000000001, run_id: 19000000001, run_attempt: 1, status: 'in_progress', runner_name: 'arc-runner-1',
  name: `Publish One Candidate And Validate Same Bytes In DEV / ${inner}`, ...patch,
})
const jobQuery = { innerJobName: inner, runnerName: 'arc-runner-1', runId: 19000000001, runAttempt: 1 }

test('selects exactly this in-progress inner publisher job on this runner', () => {
  const jobs = [
    { id: 1, name: 'Verify Tests Workflow', status: 'completed', runner_name: 'arc-runner-0', run_id: 19000000001, run_attempt: 1 },
    job({}),
    job({ id: 3, name: 'Publish One Candidate And Validate Same Bytes In DEV / Publish One Immutable Candidate And Upload Same Bytes To DEV', status: 'queued', runner_name: null }),
  ]
  assert.equal(selectPublisherJob(jobs, jobQuery), 54000000001)
})

for (const [name, jobs] of [
  ['no job', []],
  ['ambiguous jobs', [job({}), job({ id: 2 })]],
  ['another runner', [job({ runner_name: 'arc-runner-2' })]],
  ['completed job', [job({ status: 'completed' })]],
  ['bare inner name', [job({ name: inner })]],
  ['another attempt', [job({ run_attempt: 2 })]],
]) {
  test(`fails closed on ${name} when selecting the publisher job`, () => {
    assert.throws(() => selectPublisherJob(jobs, jobQuery), ProvenanceError)
  })
}

const release = () => ({
  id: 250000001, tag_name: 'v16.4', draft: false, prerelease: false, published_at: '2026-10-07T12:00:00Z',
  assets: [{ id: 300000001, name: 'BeplyCRM-v16.4.zip', state: 'uploaded', digest: zipSha256, size: 4242 }],
})
const assetQuery = { tag: 'v16.4', assetName: 'BeplyCRM-v16.4.zip', zipSha256, zipSize: 4242 }

test('binds release and asset identity to the API digest of the exact immutable bytes', () => {
  assert.deepEqual(selectReleaseAsset(release(), assetQuery), {
    release: { id: 250000001, publishedAt: '2026-10-07T12:00:00Z' },
    asset: { id: 300000001, name: 'BeplyCRM-v16.4.zip', sha256: zipSha256, sizeBytes: 4242 },
  })
})

for (const [name, mutate] of [
  ['draft release', (r) => { r.draft = true }],
  ['prerelease', (r) => { r.prerelease = true }],
  ['another tag', (r) => { r.tag_name = 'v16.5' }],
  ['missing digest', (r) => { r.assets[0].digest = null }],
  ['digest drift', (r) => { r.assets[0].digest = `sha256:${'f'.repeat(64)}` }],
  ['size drift', (r) => { r.assets[0].size = 4243 }],
  ['duplicate canonical asset', (r) => { r.assets.push({ ...r.assets[0], id: 300000002 }) }],
  ['asset still uploading', (r) => { r.assets[0].state = 'starter' }],
  ['missing publication time', (r) => { r.published_at = null }],
]) {
  test(`fails closed on ${name}`, () => {
    const value = release()
    mutate(value)
    assert.throws(() => selectReleaseAsset(value, assetQuery), ProvenanceError)
  })
}

test('accepts a tag push or a dispatch on the tag ref, never a branch or another event', () => {
  assert.equal(sourceEvent('push', 'tag', 'refs/tags/v16.4', 'v16.4'), 'push')
  assert.equal(sourceEvent('workflow_dispatch', 'tag', 'refs/tags/v16.4', 'v16.4'), 'workflow_dispatch')
  assert.throws(() => sourceEvent('workflow_dispatch', 'branch', 'refs/heads/main', 'main'), ProvenanceError)
  assert.throws(() => sourceEvent('pull_request', 'tag', 'refs/tags/v16.4', 'v16.4'), ProvenanceError)
  assert.throws(() => sourceEvent('push', 'tag', 'refs/tags/v16.5', 'v16.4'), ProvenanceError)
})
