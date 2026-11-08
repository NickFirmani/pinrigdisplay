"""Build a complete Pico application release on the artwork workstation."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from pinrig_producers.releases import validate_release


def build(output: Path, release: str, runtime: Path, runtime_version: str) -> None:
    """Build into a new directory, including generated graphics and identity."""
    if not release or len(release) > 64 or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-' for c in release):
        raise ValueError('release must be a short filename-safe identifier')
    root = Path(__file__).resolve().parents[1]
    output.mkdir(parents=True, exist_ok=False)
    subprocess.run([sys.executable, str(root / 'tools/build_pico_assets.py'), '--output', str(output / 'assets')], check=True)
    subprocess.run([sys.executable, '-m', 'tools.build_on_air_motion', '--output', str(output / 'assets')], check=True, cwd=root)
    for name in ('core', 'hardware', 'pixels', 'storage', 'main'):
        shutil.copyfile(root / 'firmware/pico' / (name + '.py'), output / (name + '.py'))
    shutil.copyfile(root / 'pinrig_protocol/commands.py', output / 'commands.py')
    shutil.copyfile(runtime, output / 'runtime.uf2')
    asset_hash = hashlib.sha256()
    for path in sorted((output / 'assets').iterdir()):
        asset_hash.update(path.name.encode())
        asset_hash.update(path.read_bytes())
    identity = {'release': release, 'protocol': 1, 'target': 'pico2w', 'runtime': runtime_version, 'assets': asset_hash.hexdigest()}
    (output / 'identity.json').write_text(json.dumps(identity))
    (output / 'release_identity.py').write_text('IDENTITY = ' + repr(identity) + '\n')
    files = {p.relative_to(output).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(output.rglob('*')) if p.is_file()}
    (output / 'manifest.json').write_text(json.dumps({'schema': 1, **identity, 'files': files}, indent=2) + '\n')
    validate_release(output)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--release', required=True)
    parser.add_argument('--runtime', type=Path, required=True, help='Pico 2 W MicroPython UF2')
    parser.add_argument('--runtime-version', required=True)
    args = parser.parse_args()
    build(args.output, args.release, args.runtime, args.runtime_version)


if __name__ == '__main__':
    main()
