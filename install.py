"""Offline skill installer: integrity check, native smoke test, reversible update."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent


def verify_payload():
    manifest = json.loads((ROOT / 'MANIFEST.json').read_text(encoding='utf-8'))
    expected = set()
    for item in manifest['files']:
        relative = PurePosixPath(item['path'])
        if relative.is_absolute() or '..' in relative.parts or '\\' in item['path'] or ':' in item['path']:
            raise ValueError('Unsafe manifest path')
        path = ROOT.joinpath(*relative.parts)
        if path.is_symlink() or ROOT not in path.resolve().parents:
            raise ValueError('Payload must stay inside the repository')
        if hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
            raise ValueError('Integrity mismatch: ' + item['path'])
        expected.add(item['path'])
    payload = ROOT / 'skills' / 'workflow-creator'
    for path in payload.rglob('*'):
        if path.is_symlink():
            raise ValueError('Symlink in skill payload')
        if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc':
            if path.relative_to(ROOT).as_posix() not in expected:
                raise ValueError('Unlisted payload: ' + str(path.relative_to(ROOT)))
    if 'skills/workflow-creator/SKILL.md' not in expected:
        raise ValueError('Missing skill in manifest')
    return payload


def check(target):
    command = [sys.executable, '-I', '-B', str(target / 'scripts' / 'foundry.py'), '--self-test']
    subprocess.run(command, check=True)


def main():
    if sys.version_info < (3, 11):
        raise ValueError('Python 3.11 or newer is required')
    parser = argparse.ArgumentParser(description=__doc__)
    default = Path(os.environ.get('CODEX_HOME', Path.home() / '.codex')) / 'skills'
    parser.add_argument('--skills-dir', type=Path, default=default,
                        help='Override skill directory; default: CODEX_HOME/skills or ~/.codex/skills')
    parser.add_argument('--check', action='store_true', help='Check existing installation; do not install')
    args = parser.parse_args()
    skill_home = args.skills_dir.expanduser().resolve()
    target = skill_home / 'workflow-creator'
    if args.check:
        check(target)
        return
    payload = verify_payload()
    if ROOT == target or ROOT in target.parents or target in ROOT.parents:
        raise ValueError('Choose an installation outside the downloaded repository')
    if target.is_symlink():
        raise ValueError('Refusing to replace a symlink installation')
    skill_home.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.workflow-creator-stage-', dir=skill_home))
    backup = None
    try:
        shutil.copytree(payload, stage, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        check(stage)
        if target.exists():
            stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
            backup_home = skill_home.parent / 'skill-backups'
            backup_home.mkdir(parents=True, exist_ok=True)
            backup = backup_home / ('workflow-creator-' + stamp)
            target.rename(backup)
        try:
            stage.rename(target)
        except OSError:
            if backup is not None:
                backup.rename(target)
            raise
    finally:
        if stage.exists():
            if stage.resolve().parent != skill_home or not stage.name.startswith('.workflow-creator-stage-'):
                raise ValueError('Refusing cleanup outside installation staging directory')
            shutil.rmtree(stage)
    print('Installed:', target)
    if backup is not None:
        print('Previous installation preserved:', backup)
    print('Open a new agent session and say: Use workflow-creator.')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as exc:
        raise SystemExit(str(exc))
