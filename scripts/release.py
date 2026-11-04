"""Check or build an explicit public file list. No network or auto-discovery of release files."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys
import zipfile

from content_checks import inspect_files

ROOT = Path(__file__).resolve().parents[1]
SKIP = {'.git', '.venv', '__pycache__'}


def read_config(root):
    data = json.loads((root / 'release.json').read_text(encoding='utf-8'))
    names = data['files']
    if not isinstance(names, list) or not names or len(names) != len(set(names)):
        raise ValueError('release.json needs a nonempty, unique file list')
    if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+(?:-[a-z0-9.]+)?', data['version']):
        raise ValueError('Invalid release version')
    for name in names:
        path = PurePosixPath(name)
        if path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name or name == 'MANIFEST.json':
            raise ValueError('Unsafe release path: ' + name)
        disk = root / name
        if not disk.is_file() or disk.is_symlink() or root.resolve() not in disk.resolve().parents:
            raise ValueError('Missing or linked release file: ' + name)
    return data


def actual_files(root):
    found = set()
    for path in root.rglob('*'):
        relative = path.relative_to(root)
        if any(x in SKIP for x in relative.parts) or path.suffix == '.pyc':
            continue
        if path.is_symlink():
            raise ValueError('Linked path in release source: ' + relative.as_posix())
        if path.is_file():
            found.add(relative.as_posix())
    return found


def inspect(root):
    config = read_config(root)
    expected = set(config['files']) | {'MANIFEST.json'}
    extra = actual_files(root) - expected
    if extra:
        raise ValueError('Unlisted files; review them before changing release.json: ' + ', '.join(sorted(extra)))
    issues = inspect_files(root, config['files'])
    if issues:
        raise ValueError(json.dumps(issues))
    # Focused private-data patterns complement the separate Gitleaks scan.
    for name in config['files']:
        text = (root / name).read_text(encoding='utf-8')
        if re.search(r'gh[pousr]_[A-Za-z0-9]{25,}|github_pat_[A-Za-z0-9_]{25,}|BEGIN [A-Z ]*PRIVATE KEY', text):
            raise ValueError('Possible secret in ' + name)
    return config


def manifest(root, config):
    return {'version': config['version'], 'files': [
        {'path': name, 'sha256': hashlib.sha256((root / name).read_bytes()).hexdigest()}
        for name in sorted(config['files'])]}


def check(root):
    config = inspect(root)
    wanted = manifest(root, config)
    current = json.loads((root / 'MANIFEST.json').read_text(encoding='utf-8'))
    if current != wanted:
        raise ValueError('Manifest is stale; review changes, then run: python scripts/release.py manifest')
    return config


def build(root, output):
    config = check(root)
    output = output.resolve()
    if root.resolve() == output or root.resolve() in output.parents:
        raise ValueError('Write the ZIP outside the source repo')
    if output.exists():
        raise ValueError('Output already exists; choose a new ZIP path')
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(config['files'] + ['MANIFEST.json']):
            archive.write(root / name, 'workflow-creator/' + name)
    with zipfile.ZipFile(output) as archive:
        if archive.testzip() is not None:
            raise ValueError('ZIP payload failed its CRC check')
        for name in config['files']:
            if archive.read('workflow-creator/' + name) != (root / name).read_bytes():
                raise ValueError('ZIP payload differs: ' + name)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['check', 'manifest', 'build'])
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.action == 'manifest':
        config = inspect(ROOT)
        (ROOT / 'MANIFEST.json').write_text(json.dumps(manifest(ROOT, config), indent=2) + '\n', encoding='utf-8')
        print('Manifest updated from the reviewed release.json file list')
    elif args.action == 'build':
        if args.output is None:
            parser.error('build needs --output outside the repo')
        print(build(ROOT, args.output))
    else:
        config = check(ROOT)
        print(f"Release {config['version']}: {len(config['files']) + 1} files, content/links/hashes passed")


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError) as error:
        raise SystemExit(str(error))
