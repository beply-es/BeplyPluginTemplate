#!/usr/bin/env node
// Builds the `beply-plugin-source-provenance-v1` carrier manifest for one immutable
// plugin release. The platform re-verifies every field against GitHub's native
// APIs (peeled tag, run, job, release asset, caller + reusable workflow bytes);
// this script only assembles the facts and fails closed on any drift.
//
// The byte format must be canonical JSON (recursively sorted keys, no
// whitespace, no trailing newline) because the platform rejects any carrier
// whose bytes differ from its canonical re-serialisation.
import { createHash } from 'node:crypto'
import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { pathToFileURL } from 'node:url'

export const MANIFEST_SCHEMA = 'beply-plugin-source-provenance-v1'
export const MANIFEST_FILE = 'plugin-source-provenance.json'

const SHA40 = /^[a-f0-9]{40}$/
const DIGEST = /^sha256:[a-f0-9]{64}$/
const REPOSITORY = /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/
const WORKFLOW_PATH = /^\.github\/workflows\/[A-Za-z0-9_.-]+\.ya?ml$/
const JOB_KEY = /^[A-Za-z_][A-Za-z0-9_-]*$/
const FS_NAME = /^[A-Za-z][A-Za-z0-9_]*$/
const DATETIME = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$/
const EVENTS = new Set(['push', 'workflow_dispatch', 'release'])

export class ProvenanceError extends Error {}

function fail(message) {
  throw new ProvenanceError(message)
}

function positiveId(value, name) {
  const number = typeof value === 'string' && /^[1-9][0-9]{0,15}$/.test(value) ? Number(value) : value
  if (!Number.isSafeInteger(number) || number <= 0) fail(`${name} must be a positive safe integer`)
  return number
}

/** Same canonical form as the platform's canonicalPluginSourceManifest. */
export function canonicalJson(value) {
  function canonical(input) {
    if (Array.isArray(input)) return input.map(canonical)
    if (input && typeof input === 'object') {
      return Object.fromEntries(
        Object.entries(input)
          .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
          .map(([key, item]) => [key, canonical(item)]),
      )
    }
    return input
  }
  return JSON.stringify(canonical(value))
}

function exactKeys(value, keys, name) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) fail(`${name} must be an object`)
  const actual = Object.keys(value).sort()
  const expected = [...keys].sort()
  if (actual.length !== expected.length || actual.some((key, index) => key !== expected[index])) {
    fail(`${name} must contain exactly ${expected.join(', ')}`)
  }
}

function boundedString(value, name, max) {
  if (typeof value !== 'string' || value.length < 1 || value.length > max) fail(`${name} is invalid`)
}

/**
 * Mirrors pluginSourceProvenanceManifestSchema (beply_node_backend_v2,
 * src/infrastructure/services/plugin-source-provenance.contract.ts): strict
 * objects, exact field set and the same bounds/patterns.
 */
export function validateManifest(manifest) {
  exactKeys(manifest, ['schema', 'source', 'release', 'asset', 'plugin'], 'manifest')
  if (manifest.schema !== MANIFEST_SCHEMA) fail('manifest.schema is invalid')
  const { source, release, asset, plugin } = manifest
  exactKeys(source, ['repository', 'repositoryId', 'commitSha', 'releaseTag', 'workflowPath', 'workflowBlobSha',
    'runId', 'runAttempt', 'publisherJobKey', 'publisherJobId', 'event', 'ref'], 'manifest.source')
  if (!REPOSITORY.test(source.repository)) fail('source.repository is invalid')
  for (const key of ['repositoryId', 'runId', 'runAttempt', 'publisherJobId']) {
    if (!Number.isSafeInteger(source[key]) || source[key] <= 0) fail(`source.${key} is invalid`)
  }
  if (!SHA40.test(source.commitSha)) fail('source.commitSha is invalid')
  boundedString(source.releaseTag, 'source.releaseTag', 200)
  if (!WORKFLOW_PATH.test(source.workflowPath)) fail('source.workflowPath is invalid')
  if (!SHA40.test(source.workflowBlobSha)) fail('source.workflowBlobSha is invalid')
  if (!JOB_KEY.test(source.publisherJobKey)) fail('source.publisherJobKey is invalid')
  if (!EVENTS.has(source.event)) fail('source.event is invalid')
  boundedString(source.ref, 'source.ref', 256)
  exactKeys(release, ['id', 'publishedAt'], 'manifest.release')
  if (!Number.isSafeInteger(release.id) || release.id <= 0) fail('release.id is invalid')
  if (typeof release.publishedAt !== 'string' || !DATETIME.test(release.publishedAt)
    || !Number.isFinite(Date.parse(release.publishedAt))) fail('release.publishedAt is invalid')
  exactKeys(asset, ['id', 'name', 'sha256', 'sizeBytes'], 'manifest.asset')
  if (!Number.isSafeInteger(asset.id) || asset.id <= 0) fail('asset.id is invalid')
  boundedString(asset.name, 'asset.name', 200)
  if (!DIGEST.test(asset.sha256)) fail('asset.sha256 is invalid')
  if (!Number.isSafeInteger(asset.sizeBytes) || asset.sizeBytes <= 0) fail('asset.sizeBytes is invalid')
  exactKeys(plugin, ['fsName', 'version'], 'manifest.plugin')
  if (!FS_NAME.test(plugin.fsName)) fail('plugin.fsName is invalid')
  boundedString(plugin.version, 'plugin.version', 100)
  return manifest
}

/** `owner/repo/.github/workflows/x.yml@refs/tags/v1` (caller workflow) -> `.github/workflows/x.yml`. */
export function callerWorkflowPath(workflowRef, repository, ref) {
  const prefix = `${repository}/`
  const suffix = `@${ref}`
  if (typeof workflowRef !== 'string' || !workflowRef.startsWith(prefix) || !workflowRef.endsWith(suffix)) {
    fail('GITHUB_WORKFLOW_REF does not belong to the caller repository and ref')
  }
  const workflowPath = workflowRef.slice(prefix.length, workflowRef.length - suffix.length)
  if (!WORKFLOW_PATH.test(workflowPath)) fail('caller workflow path is invalid')
  return workflowPath
}

/** Selects this job in the attempt: exactly one in-progress `<caller> / <inner>` job on this runner. */
export function selectPublisherJob(jobs, { innerJobName, runnerName, runId, runAttempt }) {
  const matches = jobs.filter((job) =>
    typeof job?.name === 'string'
    && job.name.endsWith(` / ${innerJobName}`)
    && job.status === 'in_progress'
    && job.runner_name === runnerName
    && job.run_id === runId
    && job.run_attempt === runAttempt)
  if (matches.length !== 1) fail(`expected exactly one in-progress publisher job, found ${matches.length}`)
  return positiveId(matches[0].id, 'publisher job id')
}

/** Exactly one uploaded canonical asset whose API digest and size equal the local immutable bytes. */
export function selectReleaseAsset(release, { tag, assetName, zipSha256, zipSize }) {
  if (release?.tag_name !== tag || release.draft !== false || release.prerelease !== false) {
    fail('release must be the published, non-prerelease release of the tag')
  }
  if (typeof release.published_at !== 'string' || !DATETIME.test(release.published_at)) {
    fail('release published_at is missing')
  }
  const assets = Array.isArray(release.assets) ? release.assets.filter((asset) => asset?.name === assetName) : []
  if (assets.length !== 1) fail('release must contain exactly one canonical asset')
  const asset = assets[0]
  if (asset.state !== 'uploaded') fail('release asset is not uploaded')
  if (asset.digest !== zipSha256) fail('release asset digest differs from the immutable ZIP')
  if (asset.size !== zipSize) fail('release asset size differs from the immutable ZIP')
  return {
    release: { id: positiveId(release.id, 'release id'), publishedAt: release.published_at },
    asset: { id: positiveId(asset.id, 'asset id'), name: assetName, sha256: zipSha256, sizeBytes: zipSize },
  }
}

export function buildManifest(facts) {
  return validateManifest({
    schema: MANIFEST_SCHEMA,
    source: {
      repository: facts.repository,
      repositoryId: facts.repositoryId,
      commitSha: facts.commitSha,
      releaseTag: facts.releaseTag,
      workflowPath: facts.workflowPath,
      workflowBlobSha: facts.workflowBlobSha,
      runId: facts.runId,
      runAttempt: facts.runAttempt,
      publisherJobKey: facts.publisherJobKey,
      publisherJobId: facts.publisherJobId,
      event: facts.event,
      ref: facts.ref,
    },
    release: facts.release,
    asset: facts.asset,
    plugin: { fsName: facts.pluginName, version: facts.pluginVersion },
  })
}

function required(name) {
  const value = process.env[name]
  if (!value || value.trim() === '') fail(`${name} is required`)
  return value.trim()
}

async function githubJson(apiPath) {
  const response = await fetch(`${process.env.GITHUB_API_URL || 'https://api.github.com'}${apiPath}`, {
    headers: {
      Authorization: `Bearer ${required('GITHUB_TOKEN')}`,
      Accept: 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
      'User-Agent': 'beply-plugin-source-provenance',
    },
    signal: AbortSignal.timeout(20_000),
  })
  if (!response.ok) fail(`GitHub API ${apiPath.split('?')[0]} returned HTTP ${response.status}`)
  return response.json()
}

async function retry(read, attempts = 6) {
  let lastError
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      return await read()
    } catch (error) {
      lastError = error
      if (attempt < attempts) await new Promise((resolve) => setTimeout(resolve, 2000 * attempt))
    }
  }
  throw lastError
}

async function main() {
  const repository = required('GITHUB_REPOSITORY')
  const ref = required('GITHUB_REF')
  const tag = required('GITHUB_REF_NAME')
  const commitSha = required('GITHUB_SHA')
  const runId = positiveId(required('GITHUB_RUN_ID'), 'GITHUB_RUN_ID')
  const runAttempt = positiveId(required('GITHUB_RUN_ATTEMPT'), 'GITHUB_RUN_ATTEMPT')
  if (required('GITHUB_EVENT_NAME') !== 'push' || required('GITHUB_REF_TYPE') !== 'tag' || ref !== `refs/tags/${tag}`) {
    fail('source provenance requires a tag push')
  }
  const pluginRoot = required('PLUGIN_ROOT')
  const zipPath = required('PLUGIN_ZIP')
  const outputDir = required('MANIFEST_DIR')
  const workflowPath = callerWorkflowPath(required('GITHUB_WORKFLOW_REF'), repository, ref)
  const peeled = execFileSync('git', ['-C', pluginRoot, 'rev-parse', '--verify', `refs/tags/${tag}^{commit}`], { encoding: 'utf8' }).trim()
  if (peeled !== commitSha) fail('release tag does not peel to the run commit')
  const workflowBlobSha = execFileSync('git', ['-C', pluginRoot, 'rev-parse', '--verify', `${commitSha}:${workflowPath}`], { encoding: 'utf8' }).trim()
  const zip = fs.readFileSync(zipPath)
  const zipSha256 = `sha256:${createHash('sha256').update(zip).digest('hex')}`
  const assetName = path.basename(zipPath)

  const selected = await retry(async () => selectReleaseAsset(
    await githubJson(`/repos/${repository}/releases/tags/${encodeURIComponent(tag)}`),
    { tag, assetName, zipSha256, zipSize: zip.length },
  ))
  const publisherJobId = await retry(async () => {
    const jobs = []
    for (let page = 1; page <= 5; page += 1) {
      const payload = await githubJson(`/repos/${repository}/actions/runs/${runId}/attempts/${runAttempt}/jobs?per_page=100&page=${page}`)
      if (!Array.isArray(payload.jobs)) fail('jobs payload is invalid')
      jobs.push(...payload.jobs)
      if (jobs.length >= Number(payload.total_count) || payload.jobs.length < 100) break
    }
    return selectPublisherJob(jobs, {
      innerJobName: required('PUBLISHER_JOB_NAME'),
      runnerName: required('RUNNER_NAME'),
      runId,
      runAttempt,
    })
  })

  const manifest = buildManifest({
    repository,
    repositoryId: positiveId(required('GITHUB_REPOSITORY_ID'), 'GITHUB_REPOSITORY_ID'),
    commitSha,
    releaseTag: tag,
    workflowPath,
    workflowBlobSha,
    runId,
    runAttempt,
    publisherJobKey: required('CALLER_JOB_KEY'),
    publisherJobId,
    event: 'push',
    ref,
    ...selected,
    pluginName: required('PLUGIN_NAME'),
    pluginVersion: required('PLUGIN_VERSION'),
  })
  const bytes = canonicalJson(manifest)
  fs.mkdirSync(outputDir, { recursive: true })
  if (fs.readdirSync(outputDir).length !== 0) fail('manifest directory must be empty')
  const manifestPath = path.join(outputDir, MANIFEST_FILE)
  fs.writeFileSync(manifestPath, bytes)
  const lines = [
    `manifest_path=${manifestPath}`,
    `publisher_job_id=${publisherJobId}`,
    `manifest_sha256=sha256:${createHash('sha256').update(bytes).digest('hex')}`,
  ]
  if (process.env.GITHUB_OUTPUT) fs.appendFileSync(process.env.GITHUB_OUTPUT, `${lines.join('\n')}\n`)
  console.log(lines.join('\n'))
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch((error) => {
    console.error(`::error::${error instanceof ProvenanceError ? error.message : 'source provenance manifest failed'}`)
    process.exit(1)
  })
}
