import json
import subprocess
import tempfile
import unittest
from pathlib import Path

SYNC = Path(__file__).resolve().parents[1] / 'template' / 'sync-template.mjs'


class TemplateSyncShaTest(unittest.TestCase):
    def test_sync_records_the_actual_source_commit_as_sha(self):
        with tempfile.TemporaryDirectory(prefix='t371-template-sync-') as tmp:
            root = Path(tmp)
            source = root / 'source'
            target = root / 'target'
            (source / '.beply').mkdir(parents=True)
            (target / '.beply').mkdir(parents=True)
            (source / '.beply/template-sync.json').write_text('{"overwrite": [], "createIfMissing": []}')
            (target / '.beply/template-lock.json').write_text(json.dumps({'sha': 'a' * 40}))
            subprocess.run(['git', 'init', '-q', str(source)], check=True)
            subprocess.run(['git', '-C', str(source), 'add', '.beply/template-sync.json'], check=True)
            subprocess.run(['git', '-C', str(source), '-c', 'user.name=Test', '-c',
                            'user.email=test@example.invalid', 'commit', '-qm', 'fixture'], check=True)
            expected = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
            result = subprocess.run(['node', str(SYNC), '--template-root', str(source),
                                     '--ref', expected, '--apply'], cwd=target, capture_output=True, text=True)
            self.assertEqual(0, result.returncode, result.stderr)
            lock = json.loads((target / '.beply/template-lock.json').read_text())
            self.assertEqual(expected, lock['commit'])
            self.assertEqual(expected, lock['sha'])

    def test_dirty_or_mismatched_source_fails_before_writing_lock(self):
        with tempfile.TemporaryDirectory(prefix='t371-template-dirty-') as tmp:
            root = Path(tmp); source = root / 'source'; target = root / 'target'
            (source / '.beply').mkdir(parents=True); (target / '.beply').mkdir(parents=True)
            policy = source / '.beply/template-sync.json'
            policy.write_text('{"overwrite": [], "createIfMissing": []}')
            lock = target / '.beply/template-lock.json'; lock.write_text('{"sha":"old"}')
            subprocess.run(['git', 'init', '-q', str(source)], check=True)
            subprocess.run(['git', '-C', str(source), 'add', '.beply/template-sync.json'], check=True)
            subprocess.run(['git', '-C', str(source), '-c', 'user.name=Test', '-c',
                            'user.email=test@example.invalid', 'commit', '-qm', 'fixture'], check=True)
            expected = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
            def sync(ref):
                return subprocess.run(['node', str(SYNC), '--template-root', str(source), '--ref', ref,
                                       '--apply'], cwd=target, capture_output=True, text=True)
            mismatch = sync('b' * 40)
            self.assertNotEqual(0, mismatch.returncode)
            self.assertEqual('{"sha":"old"}', lock.read_text())
            policy.write_text('{"overwrite": [], "createIfMissing": [], "modified": true}')
            dirty = sync(expected)
            self.assertNotEqual(0, dirty.returncode)
            self.assertEqual('{"sha":"old"}', lock.read_text())

    def test_remote_sync_accepts_an_exact_commit_sha(self):
        with tempfile.TemporaryDirectory(prefix='t371-template-sha-ref-') as tmp:
            root = Path(tmp); source = root / 'source'; target = root / 'target'
            (source / '.beply').mkdir(parents=True); target.mkdir()
            (source / '.beply/template-sync.json').write_text('{"overwrite": [], "createIfMissing": []}')
            subprocess.run(['git', 'init', '-q', str(source)], check=True)
            subprocess.run(['git', '-C', str(source), 'add', '.beply/template-sync.json'], check=True)
            subprocess.run(['git', '-C', str(source), '-c', 'user.name=Test', '-c',
                            'user.email=test@example.invalid', 'commit', '-qm', 'fixture'], check=True)
            expected = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
            result = subprocess.run(['node', str(SYNC), '--repo', str(source), '--ref', expected, '--apply'],
                                    cwd=target, capture_output=True, text=True)
            self.assertEqual(0, result.returncode, result.stderr)
            lock = json.loads((target / '.beply/template-lock.json').read_text())
            self.assertEqual(expected, lock['sha'])


if __name__ == '__main__':
    unittest.main()
