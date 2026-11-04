"""Run release checks and both nonempty unittest suites."""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
subprocess.run([sys.executable, '-B', str(ROOT / 'scripts' / 'release.py'), 'check'], env=env, check=True)
for folder in [ROOT / 'tests', ROOT / 'skills' / 'workflow-creator' / 'runtime' / 'tests']:
    subprocess.run([sys.executable, '-B', str(ROOT / 'scripts' / 'run_suite.py'), str(folder)],
                   cwd=ROOT, env=env, check=True)
print('All release, installer, example and runtime checks passed')
