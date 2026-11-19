"""Build an offline Linux wheelhouse for one role on its target platform."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from shared.display_contracts.commands import identifier
from shared.release_manifests.software import SOFTWARE_ROLES, validate_software


def build(output: Path, release: str, role: str) -> None:
    identifier(release, 'release')
    if release in ('.', '..', 'current', 'current.new'):
        raise ValueError('reserved release name')
    if role not in SOFTWARE_ROLES:
        raise ValueError('invalid software role')
    root = Path(__file__).resolve().parents[1]
    output.mkdir(parents=True, exist_ok=False)
    wheels = output / 'wheels'
    wheels.mkdir()
    subprocess.run([sys.executable, '-m', 'pip', 'wheel', '--wheel-dir', str(wheels),
                    str(root / 'shared'), str(root / role)], check=True)

    # Embed the same validator in the standalone bootstrap used before pip runs.
    installer = (root / 'tools/install_linux.py').read_text()
    validator = (root / 'shared/release_manifests/software.py').read_text()
    shared_import = 'from shared.release_manifests.software import SOFTWARE_ROLES, validate_software'
    if installer.count(shared_import) != 1:
        raise ValueError('bootstrap must import the shared manifest validator once')
    (output / 'install_linux.py').write_text(installer.replace(shared_import, validator.rstrip()))

    files = {path.relative_to(output).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
             for path in sorted(output.rglob('*')) if path.is_file()}
    (output / 'software.json').write_text(json.dumps(
        {'schema': 1, 'protocol': 1, 'target': 'linux', 'role': role,
         'release': release, 'files': files}, indent=2) + '\n')
    validate_software(output, role=role)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--release', required=True)
    parser.add_argument('--role', choices=SOFTWARE_ROLES, required=True)
    args = parser.parse_args()
    build(args.output, args.release, args.role)


if __name__ == '__main__':
    main()
