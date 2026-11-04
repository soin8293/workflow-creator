import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
spec = importlib.util.spec_from_file_location('release_tools', ROOT / 'scripts' / 'release.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / 'source'
        self.root.mkdir()
        (self.root / 'README.md').write_text('# Example\n\nA small fake release.\n', encoding='utf-8')
        (self.root / 'release.json').write_text(json.dumps(
            {'version': '0.1.0-rc.3', 'files': ['README.md', 'release.json']}), encoding='utf-8')
        config = release.inspect(self.root)
        (self.root / 'MANIFEST.json').write_text(json.dumps(release.manifest(self.root, config)), encoding='utf-8')

    def tearDown(self):
        self.temp.cleanup()

    def test_current_release_and_zip_payload_match(self):
        self.assertEqual(release.check(self.root)['version'], '0.1.0-rc.3')
        archive = release.build(self.root, self.root.parent / 'release.zip')
        with zipfile.ZipFile(archive) as data:
            self.assertIsNone(data.testzip())
            self.assertEqual(data.read('workflow-creator/README.md'), (self.root / 'README.md').read_bytes())

    def test_stale_hash_is_rejected_without_updating_manifest(self):
        before = (self.root / 'MANIFEST.json').read_bytes()
        (self.root / 'README.md').write_text('# Changed\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'stale'):
            release.check(self.root)
        self.assertEqual((self.root / 'MANIFEST.json').read_bytes(), before)

    def test_unlisted_file_is_not_silently_added(self):
        (self.root / 'local-notes.txt').write_text('fake notes', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Unlisted'):
            release.inspect(self.root)

    def test_missing_file_and_unsafe_path_fail(self):
        (self.root / 'README.md').unlink()
        with self.assertRaisesRegex(ValueError, 'Missing'):
            release.check(self.root)
        (self.root / 'release.json').write_text(json.dumps({'version': '0.1.0', 'files': ['../outside.txt']}))
        with self.assertRaisesRegex(ValueError, 'Unsafe'):
            release.read_config(self.root)

    def test_bad_local_link_is_rejected(self):
        (self.root / 'README.md').write_text('# Demo\n\n[Missing](missing.md)\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'missing-local-link'):
            release.inspect(self.root)

    def test_private_file_type_is_rejected(self):
        (self.root / 'fixture.db').write_text('fake test bytes', encoding='utf-8')
        config = json.loads((self.root / 'release.json').read_text())
        config['files'].append('fixture.db')
        (self.root / 'release.json').write_text(json.dumps(config))
        with self.assertRaisesRegex(ValueError, 'private-data-format'):
            release.inspect(self.root)

    def test_build_refuses_in_source_or_existing_output(self):
        with self.assertRaisesRegex(ValueError, 'outside'):
            release.build(self.root, self.root / 'release.zip')
        output = self.root.parent / 'saved.zip'
        output.write_bytes(b'preserve previous release')
        with self.assertRaisesRegex(ValueError, 'already exists'):
            release.build(self.root, output)
        self.assertEqual(output.read_bytes(), b'preserve previous release')

    def test_suite_runner_rejects_zero_tests(self):
        empty = self.root.parent / 'empty-tests'
        empty.mkdir()
        result = subprocess.run([sys.executable, '-B', str(ROOT / 'scripts' / 'run_suite.py'), str(empty)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('No discoverable tests', result.stderr)
