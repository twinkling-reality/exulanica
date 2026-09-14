"""Verify the actual preparation inputs before serving cached or newly built characters."""
import hashlib
import json
import subprocess
from pathlib import Path


def file_digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def tree_digest(root):
    """Bind relative names and bytes; generated Python bytecode is not a source input."""
    records = []
    for path in sorted(Path(root).rglob('*')):
        relative = path.relative_to(root)
        if '__pycache__' in relative.parts or path.suffix in ('.pyc', '.pyo'):
            continue
        if path.is_symlink():
            raise ValueError('Preparation input contains a symlink: ' + str(relative))
        if path.is_file():
            records.append([relative.as_posix(), file_digest(path)])
    return hashlib.sha256(json.dumps(records, separators=(',', ':')).encode()).hexdigest()


def verify_inputs(source, blender, family_root):
    lock = json.loads((family_root / 'source-lock.json').read_text())
    repo = source / 'mpfb2'
    head = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip()
    if head != lock['mpfbCommit']:
        raise ValueError('MPFB source does not match the pinned preparation version')
    dirty = subprocess.check_output(['git', '-C', str(repo), 'status', '--porcelain', '--untracked-files=all'], text=True)
    if dirty.strip():
        raise ValueError('MPFB preparation source is dirty; restore the pinned source before building')
    animation = (family_root / lock['animationSource']).resolve()
    actual = {
        'mpfbTreeSha256': tree_digest(repo / 'src'),
        'systemAssetsTreeSha256': tree_digest(source / 'system-assets'),
        'animationSha256': file_digest(animation),
        'blenderBinarySha256': file_digest(blender),
        'licenseReceipts': {
            'mpfbAssets': file_digest(repo / 'LICENSE.ASSETS.md'),
            'mpfbCode': file_digest(repo / 'LICENSE.CODE.md'),
            'distributedAssets': file_digest(family_root / 'LICENSE.md'),
            'animationAssets': file_digest(animation.parent / 'men-LICENSE.txt'),
            'animationImport': file_digest(animation.with_suffix('.import.json')),
        },
    }
    for key, value in actual.items():
        if value != lock[key]:
            raise ValueError('Preparation input does not match its pinned receipt: ' + key)
    # Check the pinned executable before running it; version/build identity is also explicit.
    version = subprocess.check_output([str(blender), '--version'], text=True, timeout=15)
    if version.splitlines()[0] != lock['blenderVersion'] or f"build hash: {lock['blenderBuildHash']}" not in version:
        raise ValueError('Blender version or build does not match the preparation receipt')
    actual.update(mpfbCommit=head, blenderVersion=lock['blenderVersion'], blenderBuildHash=lock['blenderBuildHash'],
                  systemAssetsArchiveSha256=lock['systemAssetsSha256'])
    return actual


def preparation_identity(inputs, family_root):
    scripts = Path(__file__).parent
    return {
        'inputs': inputs,
        'family': file_digest(family_root / 'family.json'),
        'sourceLock': file_digest(family_root / 'source-lock.json'),
        'scripts': {name: file_digest(scripts / name) for name in ['inputs.py', 'blender_build.py', 'preview_server.py']},
    }


def cache_key(identity, recipe):
    return hashlib.sha256(json.dumps([identity, recipe], sort_keys=True, separators=(',', ':')).encode()).hexdigest()
