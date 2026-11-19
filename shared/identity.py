"""Installed software identity, distinct from wire and status schema versions."""
from importlib.metadata import PackageNotFoundError, version
import json
from pathlib import Path
import sys


def software_identity(distribution: str) -> dict:
    """Report the package version and immutable deployment bundle identity."""
    try:
        package = version(distribution)
    except PackageNotFoundError:
        package = 'uninstalled'
    path = Path(sys.prefix) / 'release.json'
    release = json.loads(path.read_text()).get('release') if path.exists() else None
    return {'software_version': package, 'software_release': release}
