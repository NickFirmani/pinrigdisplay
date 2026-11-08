"""Build an offline Linux rig wheelhouse; run on the target OS/architecture."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--release', required=True)
    args = parser.parse_args()
    from pinrig_protocol.commands import identifier
    identifier(args.release, 'release')
    root = Path(__file__).resolve().parents[1]
    args.output.mkdir(parents=True, exist_ok=False)
    wheels = args.output / 'wheels'
    wheels.mkdir()
    subprocess.run([sys.executable, '-m', 'pip', 'wheel', '--wheel-dir', str(wheels),
                    str(root / 'pinrig_protocol'), str(root / 'pinrig_host'),
                    str(root / 'pinrig_producers') + '[rig,obs]', 'mpremote'], check=True)
    shutil.copyfile(root / 'tools/install_linux.py', args.output / 'install_linux.py')
    paths = [p for p in args.output.rglob('*') if p.is_file()]
    (args.output / 'software.json').write_text(json.dumps({'schema': 1, 'protocol': 1, 'target': 'linux', 'release': args.release,
        'files': {p.relative_to(args.output).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}}, indent=2))


if __name__ == '__main__':
    main()
