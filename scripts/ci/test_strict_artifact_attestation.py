"""Execute the real attester and workflow guards with synthetic keys only."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from zipfile import ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / 'scripts/ci/build_plugin_artifact_attestation.mjs'


class StrictArtifactAttestationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Ephemeral test key, captured in memory; never written or logged.
        code = "const c=require('node:crypto');const k=c.generateKeyPairSync('ed25519');console.log(JSON.stringify({private:k.privateKey.export({type:'pkcs8',format:'der'}).toString('base64'),public:k.publicKey.export({type:'spki',format:'der'}).toString('base64')}));"
        cls.keys = json.loads(subprocess.check_output(['node', '-e', code], text=True))

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.directory = Path(tmp.name)
        self.plugin = self.directory / 'plugin'
        (self.plugin / 'tests').mkdir(parents=True)
        self.composer = self.plugin / 'composer.lock'
        self.composer.write_text(json.dumps({'packages': [{'name': 'fixture/library', 'version': '1.2.3'}]}))
        self.npm = self.plugin / 'tests/package-lock.json'
        self.npm.write_text(json.dumps({'packages': {'node_modules/fixture-helper': {'name': 'fixture-helper', 'version': '4.5.6', 'dev': True}}}))
        self.asset = self.directory / 'PolicyFixture-v1.0.zip'
        with ZipFile(self.asset, 'w') as z:
            info = ZipInfo('PolicyFixture/facturascripts.ini', (1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            z.writestr(info, "name = 'PolicyFixture'\nversion = 1.0\n")
        self.output = self.directory / 'output'
        self.sbom = self.directory / 'PolicyFixture-1.0-sbom.cdx.json'

    def invoke(self, *, strict='true', key=True, key_id=True, **changes):
        self.output.unlink(missing_ok=True)
        self.sbom.unlink(missing_ok=True)
        env = {'PATH': os.environ['PATH'], 'PLUGIN_NAME': 'PolicyFixture', 'PLUGIN_VERSION': '1.0',
               'PLUGIN_ZIP': str(self.asset), 'PLUGIN_ROOT': str(self.plugin), 'SOURCE_SHA': 'a'*40,
               'PLUGIN_RELEASE_TRACK': 'main', 'PLUGIN_ARTIFACT_PREFIX': 'plugins/dev',
               'REQUIRE_ARTIFACT_SIGNATURE': strict, 'GITHUB_OUTPUT': str(self.output),
               'PLUGIN_ARTIFACT_SIGNING_PRIVATE_KEY': self.keys['private'] if key else '',
               'PLUGIN_ARTIFACT_SIGNATURE_KEY_ID': 'synthetic-policy-key' if key_id else '', **changes}
        if strict is None:
            env.pop('REQUIRE_ARTIFACT_SIGNATURE')
        result = subprocess.run(['node', str(HELPER)], env=env, text=True, capture_output=True)
        values = dict(line.split('=', 1) for line in self.output.read_text().splitlines()) if self.output.exists() else {}
        return result, values

    def test_default_sbom_is_byte_identical(self):
        for strict in (None, 'false'):
            with self.subTest(policy=strict):
                run, values = self.invoke(strict=strict, key=False, key_id=False)
                self.assertEqual(0, run.returncode, run.stderr)
                self.assertEqual('false', values['has_attestation'])
                self.assertEqual('2cf688a846fc90c444d35804df701a0a0d32920d95538bcaa12daafd322ed5d9', hashlib.sha256(self.sbom.read_bytes()).hexdigest())

    def test_optional_signature_keeps_the_previous_sbom_format(self):
        run, values = self.invoke(strict='false')
        self.assertEqual(0, run.returncode, run.stderr)
        self.assertEqual('true', values['has_attestation'])
        self.assertEqual('2cf688a846fc90c444d35804df701a0a0d32920d95538bcaa12daafd322ed5d9', hashlib.sha256(self.sbom.read_bytes()).hexdigest())
        self.assertNotIn('sbom_component_count', values)

    def test_strict_mode_rejects_missing_key_or_id_before_outputs(self):
        for key, key_id in ((False, False), (True, False), (False, True)):
            with self.subTest(key=key, key_id=key_id):
                run, values = self.invoke(key=key, key_id=key_id)
                self.assertNotEqual(0, run.returncode)
                self.assertEqual({}, values)
                self.assertFalse(self.sbom.exists())

    def test_strict_signature_covers_complete_dependency_inventory(self):
        run, out = self.invoke()
        self.assertEqual(0, run.returncode, run.stderr)
        self.assertEqual('true', out['has_attestation'])
        self.assertEqual('0f49e89bc9d939d4db77d20fa901b5396d77bbf22050ea4fb6afd0b3ad3d9154', hashlib.sha256(self.sbom.read_bytes()).hexdigest())
        sbom = json.loads(self.sbom.read_text())
        self.assertEqual(['pkg:composer/fixture/library@1.2.3', 'pkg:npm/fixture-helper@4.5.6'],
                         [c['bom-ref'] for c in sbom.get('components', [])])
        self.assertIn('dependencies', sbom)
        self.assertEqual({'ref': 'pkg:generic/policyfixture@1.0', 'dependsOn': [c['bom-ref'] for c in sbom['components']]}, sbom['dependencies'][0])
        props = {p['name']: p['value'] for p in sbom['metadata']['component']['properties']}
        self.assertIn('beply:composerLockSha256', props)
        self.assertIn('beply:npmLockSha256', props)
        self.assertEqual('sha256:'+hashlib.sha256(self.composer.read_bytes()).hexdigest(), props['beply:composerLockSha256'])
        self.assertEqual('sha256:'+hashlib.sha256(self.npm.read_bytes()).hexdigest(), props['beply:npmLockSha256'])
        self.assertEqual('sha256:'+hashlib.sha256(self.sbom.read_bytes()).hexdigest(), out['sbom_checksum'])
        self.assertEqual('2', out['sbom_component_count'])
        payload = f"beply-plugin-artifact-v1\nartifact={out['artifact_checksum']}\nsbom={out['sbom_checksum']}\n"
        code = "const c=require('node:crypto');const fs=require('node:fs');const x=JSON.parse(fs.readFileSync(0,'utf8'));process.exit(c.verify(null,Buffer.from(x.payload),c.createPublicKey({key:Buffer.from(x.public,'base64'),format:'der',type:'spki'}),Buffer.from(x.signature,'base64'))?0:1);"
        for changed, expected in ((payload, 0), (payload+'tamper', 1)):
            verify = subprocess.run(['node', '-e', code], input=json.dumps({'public': self.keys['public'], 'signature': out['artifact_signature'], 'payload': changed}), text=True, capture_output=True)
            self.assertEqual(expected, verify.returncode)

    def test_bad_lock_data_and_links_fail_closed(self):
        original = self.composer.read_text()
        cases = ['invalid-json', 'null', 'false', '[]', json.dumps({'packages': 'unknown'}), json.dumps({'packages': [{'name': 'fixture/no-version'}]})]
        for bad in cases:
            with self.subTest(lock=bad):
                self.composer.write_text(bad)
                run, values = self.invoke()
                self.assertNotEqual(0, run.returncode)
                self.assertEqual({}, values)
        self.composer.write_text(original)
        outside = self.directory / 'outside.lock'
        outside.write_text(original)
        self.composer.unlink()
        self.composer.symlink_to(outside)
        run, values = self.invoke()
        self.assertNotEqual(0, run.returncode)
        self.assertEqual({}, values)

    def test_invalid_policy_or_missing_source_root_cannot_downgrade(self):
        for changes in ({'strict': 'TRUE'}, {'PLUGIN_ROOT': ''}):
            with self.subTest(changes=changes):
                run, values = self.invoke(**changes)
                self.assertNotEqual(0, run.returncode)
                self.assertEqual({}, values)




if __name__ == '__main__':
    unittest.main(verbosity=2)
