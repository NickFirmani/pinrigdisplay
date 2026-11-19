"""Apply a staged source export and remove files managed by earlier exports."""
import json
from pathlib import Path
import sys


def update(source: Path, destination: Path) -> None:
    """Refresh the source tree without removing files outside the export."""
    if destination.is_symlink():
        raise ValueError(f'destination is a symlink: {destination}')
    destination.mkdir(exist_ok=True)
    manifest = destination / '.pinrig-source-files.json'
    if manifest.is_symlink():
        raise ValueError(f'source manifest is a symlink: {manifest}')
    previous = set(json.loads(manifest.read_text())) if manifest.is_file() else set()
    files = set()
    for path in sorted(source.rglob('*')):
        name = path.relative_to(source)
        target = destination / name
        if (destination / name.parent).resolve() != destination / name.parent:
            raise ValueError(f'source path crosses a symlink: {target}')
        if path.is_dir() and not path.is_symlink():
            if target.is_symlink():
                raise ValueError(f'source directory conflicts with symlink: {target}')
            target.mkdir(exist_ok=True)
        else:
            path.replace(target)
            files.add(name.as_posix())

    for name in previous - files:
        relative = Path(name)
        if relative.is_absolute() or '..' in relative.parts or not relative.parts:
            raise ValueError(f'invalid path in source manifest: {name}')
        target = destination / relative
        if target.parent.resolve() == target.parent and (target.is_file() or target.is_symlink()):
            target.unlink()
    next_manifest = source / '.pinrig-source-files.json'
    next_manifest.write_text(json.dumps(sorted(files)) + '\n')
    next_manifest.replace(manifest)
    print(f'Updated source at {destination}')


if __name__ == '__main__':
    update(Path(sys.argv[1]), Path(sys.argv[2]))
