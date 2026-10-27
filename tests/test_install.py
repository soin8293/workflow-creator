"""Offline installation isolation, update preservation and failure rejection."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        self.skills = self.home / 'skills'
        self.target = self.skills / 'workflow-creator'
        self.env = dict(os.environ, PYTHONPATH='', WORKFLOW_FOUNDRY_HOME='/missing-external-runtime',
                        PYTHONDONTWRITEBYTECODE='1')

    def tearDown(self):
        self.temp.cleanup()

    def install(self, root=ROOT, *args):
        return subprocess.run([sys.executable, '-I', '-B', str(root / 'install.py'),
                               '--skills-dir', str(self.skills), *args],
                              cwd=self.home, env=self.env, capture_output=True, text=True)

    def copy_repo(self):
        copied = self.home / 'download'
        shutil.copytree(ROOT, copied, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        return copied

    def test_clean_install_and_native_cli_without_external_engine(self):
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.install(ROOT, '--check').returncode, 0)
        result = subprocess.run([sys.executable, '-I', '-B',
                                 str(self.target / 'scripts' / 'foundry.py'), '--help'],
                                cwd=self.home, env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('compile', result.stdout)

    def test_update_preserves_old_install_outside_skill_discovery(self):
        self.assertEqual(self.install().returncode, 0)
        (self.target / 'local-marker.txt').write_text('old installation', encoding='utf-8')
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stderr)
        backups = list((self.home / 'skill-backups').glob('workflow-creator-*'))
        self.assertEqual(len(backups), 1)
        self.assertEqual((backups[0] / 'local-marker.txt').read_text(), 'old installation')
        self.assertFalse((self.target / 'local-marker.txt').exists())
        self.assertEqual(len(list(self.skills.iterdir())), 1)

    def test_corrupt_payload_is_rejected_before_installation(self):
        root = self.copy_repo()
        (root / 'skills' / 'workflow-creator' / 'SKILL.md').write_text('corrupt', encoding='utf-8')
        result = self.install(root)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Integrity mismatch', result.stderr)
        self.assertFalse(self.target.exists())

    def test_failed_runtime_check_keeps_current_installation(self):
        self.assertEqual(self.install().returncode, 0)
        (self.target / 'local-marker.txt').write_text('preserve', encoding='utf-8')
        root = self.copy_repo()
        path = root / 'skills' / 'workflow-creator' / 'scripts' / 'foundry.py'
        path.write_text('raise SystemExit("injected unavailable runtime")', encoding='utf-8')
        manifest = json.loads((root / 'MANIFEST.json').read_text(encoding='utf-8'))
        for item in manifest['files']:
            if item['path'] == path.relative_to(root).as_posix():
                item['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        (root / 'MANIFEST.json').write_text(json.dumps(manifest), encoding='utf-8')
        result = self.install(root)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.target / 'local-marker.txt').read_text(), 'preserve')
        self.assertFalse(list(self.skills.glob('.workflow-creator-stage-*')))


if __name__ == '__main__':
    unittest.main(verbosity=2)
