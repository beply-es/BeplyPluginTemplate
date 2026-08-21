import { createHash, createPrivateKey, sign } from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'

const POLICY_VERSION = 'beply-plugin-artifact-v1'

function required(name) {
  const value = process.env[name]
  if (!value || value.trim() === '') {
    throw new Error(`${name} is required`)
  }
  return value.trim()
}

function optional(name) {
  const value = process.env[name]
  return value && value.trim() !== '' ? value.trim() : ''
}

function sha256(value) {
  return `sha256:${createHash('sha256').update(value).digest('hex')}`
}

function readJson(pathname) {
  if (!pathname || !fs.existsSync(pathname)) {
    return null
  }
  return JSON.parse(fs.readFileSync(pathname, 'utf8'))
}

function dependencyRef(ecosystem, name, version) {
  if (ecosystem === 'composer') {
    return `pkg:composer/${name}@${version}`
  }
  const encoded = encodeURIComponent(name).replaceAll('%2F', '/')
  return `pkg:npm/${encoded}@${version}`
}

function packageNameFromLockPath(lockPath, declaredName) {
  if (declaredName) {
    return declaredName
  }
  const tail = String(lockPath).split('node_modules/').pop() || ''
  const segments = tail.split('/').filter(Boolean)
  return segments[0]?.startsWith('@') ? segments.slice(0, 2).join('/') : (segments[0] || '')
}

function lockedDependencies(pluginRoot) {
  const byRef = new Map()
  const lockHashes = []
  const composerPath = path.join(pluginRoot, 'composer.lock')
  const composer = readJson(composerPath)
  if (composer) {
    lockHashes.push({ name: 'beply:composerLockSha256', value: sha256(fs.readFileSync(composerPath)) })
    for (const item of Array.isArray(composer.packages) ? composer.packages : []) {
      const name = String(item?.name || '')
      const version = String(item?.version || '')
      if (!name || !version) continue
      const [group = '', packageName = name] = name.split('/', 2)
      const ref = dependencyRef('composer', name, version)
      byRef.set(ref, {
        type: 'library',
        'bom-ref': ref,
        group,
        name: packageName,
        version,
        purl: ref,
        properties: [{ name: 'beply:dependencyScope', value: 'runtime' }],
      })
    }
  }

  const npmCandidates = [path.join(pluginRoot, 'package-lock.json'), path.join(pluginRoot, 'tests/package-lock.json')]
  const npmPath = npmCandidates.find(candidate => fs.existsSync(candidate))
  const npm = readJson(npmPath)
  if (npm && npmPath) {
    lockHashes.push({ name: 'beply:npmLockSha256', value: sha256(fs.readFileSync(npmPath)) })
    for (const [lockPath, item] of Object.entries(npm.packages || {})) {
      if (!lockPath || !item || typeof item !== 'object') continue
      const name = packageNameFromLockPath(lockPath, item.name)
      const version = String(item.version || '')
      if (!name || !version) continue
      const ref = dependencyRef('npm', name, version)
      const scope = item.dev === true ? 'development' : 'runtime'
      const existing = byRef.get(ref)
      if (existing && existing.properties[0].value === 'runtime') continue
      byRef.set(ref, {
        type: 'library',
        'bom-ref': ref,
        name,
        version,
        purl: ref,
        properties: [{ name: 'beply:dependencyScope', value: scope }],
      })
    }
  }

  return {
    components: [...byRef.values()].sort((left, right) => left['bom-ref'].localeCompare(right['bom-ref'])),
    lockHashes: lockHashes.sort((left, right) => left.name.localeCompare(right.name)),
  }
}

function normalizeTrack(value) {
  return (value || 'main').trim().replace(/^refs\/heads\//, '') || 'main'
}

function normalizePrefix(value) {
  return (value || 'plugins').trim().replace(/^\/+|\/+$/g, '') || 'plugins'
}

function pluginSlug(name) {
  return name.toLowerCase().replace(/[^a-z0-9-]/g, '')
}

function artifactKey(slug, version, track, prefix) {
  return track === 'main'
    ? `${prefix}/${slug}/${version}/plugin.zip`
    : `${prefix}/${track}/${slug}/${version}/plugin.zip`
}

function deterministicUuid(seed) {
  const hex = createHash('sha256').update(seed).digest('hex')
  return [
    hex.slice(0, 8),
    hex.slice(8, 12),
    `4${hex.slice(13, 16)}`,
    ((parseInt(hex.slice(16, 18), 16) & 0x3f) | 0x80).toString(16).padStart(2, '0')
      + hex.slice(18, 20),
    hex.slice(20, 32),
  ].join('-')
}

function buildSbom(input) {
  const checksumHex = input.artifactChecksum.replace(/^sha256:/, '')
  const rootRef = `pkg:generic/${input.pluginSlug}@${input.version}`
  const properties = [
    { name: 'beply:releaseTrack', value: input.releaseTrack },
    { name: 'beply:artifactKey', value: input.artifactKey },
    { name: 'beply:fileSize', value: String(input.fileSize) },
    ...input.lockHashes,
  ]
  if (input.sourceRepoFullName) {
    properties.push({ name: 'beply:sourceRepoFullName', value: input.sourceRepoFullName })
  }
  if (input.sourceReleaseTag) {
    properties.push({ name: 'beply:sourceReleaseTag', value: input.sourceReleaseTag })
  }
  const externalReferences = [{ type: 'distribution', url: input.artifactKey }]
  if (input.sourceReleaseUrl) {
    externalReferences.push({ type: 'release-notes', url: input.sourceReleaseUrl })
  }
  return Buffer.from(`${JSON.stringify({
    bomFormat: 'CycloneDX',
    specVersion: '1.5',
    serialNumber: `urn:uuid:${deterministicUuid([
      input.pluginSlug,
      input.version,
      input.releaseTrack,
      checksumHex,
    ].join('|'))}`,
    version: 1,
    metadata: {
      timestamp: '1970-01-01T00:00:00.000Z',
      component: {
        type: 'application',
        'bom-ref': rootRef,
        group: 'beply-plugin',
        name: input.pluginSlug,
        version: input.version,
        purl: rootRef,
        hashes: [{ alg: 'SHA-256', content: checksumHex }],
        properties,
        externalReferences,
      },
    },
    components: input.components,
    dependencies: [{ ref: rootRef, dependsOn: input.components.map(component => component['bom-ref']) }],
  }, null, 2)}\n`, 'utf8')
}

function privateKeyFrom(value) {
  if (value.includes('BEGIN PRIVATE KEY')) {
    return createPrivateKey(value)
  }
  return createPrivateKey({ key: Buffer.from(value, 'base64'), format: 'der', type: 'pkcs8' })
}

function appendOutputs(values) {
  if (!process.env.GITHUB_OUTPUT) {
    for (const [key, value] of Object.entries(values)) {
      console.log(`${key}=${value}`)
    }
    return
  }
  fs.appendFileSync(
    process.env.GITHUB_OUTPUT,
    `${Object.entries(values).map(([key, value]) => `${key}=${value}`).join('\n')}\n`,
    'utf8',
  )
}

const name = required('PLUGIN_NAME')
const version = required('PLUGIN_VERSION')
const zipPath = required('PLUGIN_ZIP')
const sourceSha = required('SOURCE_SHA')
const releaseTrack = normalizeTrack(optional('PLUGIN_RELEASE_TRACK'))
const prefix = normalizePrefix(optional('PLUGIN_ARTIFACT_PREFIX'))
const sourceRepoFullName = optional('SOURCE_REPO_FULL_NAME')
const sourceReleaseTag = optional('SOURCE_RELEASE_TAG')
const sourceReleaseUrl = optional('SOURCE_RELEASE_URL')
const pluginRoot = path.resolve(required('PLUGIN_ROOT'))
const signingKey = optional('PLUGIN_ARTIFACT_SIGNING_PRIVATE_KEY')
const signingKeyId = optional('PLUGIN_ARTIFACT_SIGNATURE_KEY_ID')
const requireSignature = optional('REQUIRE_ARTIFACT_SIGNATURE') === 'true'
const slug = pluginSlug(name)
const zipBuffer = fs.readFileSync(zipPath)
const artifactChecksum = sha256(zipBuffer)
const key = artifactKey(slug, version, releaseTrack, prefix)
const sbomUrl = key.replace(/\/plugin\.zip$/, '/sbom.cdx.json')
const dependencies = lockedDependencies(pluginRoot)
const sbom = buildSbom({
  pluginSlug: slug,
  version,
  releaseTrack,
  artifactKey: key,
  artifactChecksum,
  fileSize: zipBuffer.length,
  sourceSha,
  sourceRepoFullName,
  sourceReleaseTag,
  sourceReleaseUrl,
  ...dependencies,
})
const sbomChecksum = sha256(sbom)
const sbomPath = path.join(path.dirname(zipPath), `${name}-${version}-sbom.cdx.json`)
fs.writeFileSync(sbomPath, sbom)
const outputs = {
  artifact_checksum: artifactChecksum,
  file_size: String(zipBuffer.length),
  sbom_path: sbomPath,
  sbom_url: sbomUrl,
  sbom_checksum: sbomChecksum,
  artifact_policy_version: POLICY_VERSION,
  sbom_component_count: String(dependencies.components.length),
  has_attestation: 'false',
}
if (requireSignature && (!signingKey || !signingKeyId)) {
  throw new Error('Artifact signing key and key ID are required by release policy')
}
if (signingKey || signingKeyId) {
  if (!signingKey || !signingKeyId) {
    throw new Error('Both artifact signing key and key ID are required')
  }
  const payload = `${POLICY_VERSION}\nartifact=${artifactChecksum}\nsbom=${sbomChecksum}\n`
  outputs.artifact_signature = sign(null, Buffer.from(payload), privateKeyFrom(signingKey)).toString('base64')
  outputs.artifact_signature_key_id = signingKeyId
  outputs.has_attestation = 'true'
}
appendOutputs(outputs)
