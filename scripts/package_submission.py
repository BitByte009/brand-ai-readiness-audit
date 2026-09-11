"""Build a clean submission ZIP from the workspace root; never includes caches."""
import argparse
from pathlib import Path
import zipfile
import tempfile
import os

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {'.git', '.pytest_cache', '__pycache__', '.venv', 'dist', '.DS_Store'}


def package(output):
    output = Path(output).resolve()
    members = [p for p in sorted(ROOT.rglob('*')) if p.is_file()
               and not p.is_symlink() and not EXCLUDED.intersection(p.relative_to(ROOT).parts)
               and p.suffix.lower() not in {'.pyc', '.pyo', '.zip'}
               and p.name not in {'report.json', 'report.md', 'observations.json'}
               and p != output]
    if any(p.suffix.lower() in {'.pt', '.pth', '.onnx', '.safetensors', '.ckpt'} for p in members):
        raise ValueError('Model weights must not be submitted')
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, candidate = tempfile.mkstemp(prefix='.submission-', suffix='.zip', dir=output.parent)
    os.close(descriptor)
    candidate = Path(candidate)
    try:
        with zipfile.ZipFile(candidate, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for path in members:
                info = zipfile.ZipInfo(path.relative_to(ROOT).as_posix(), date_time=(2026, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                archive.writestr(info, path.read_bytes())
        if candidate.stat().st_size > 50_000_000:
            raise ValueError('Submission exceeds 50 MB')
        with zipfile.ZipFile(candidate) as archive:
            if 'marketplace.json' not in archive.namelist() or archive.testzip() is not None:
                raise ValueError('Invalid submission archive')
        os.replace(candidate, output)  # replaces the old ZIP only after validation
    finally:
        candidate.unlink(missing_ok=True)
    return len(members), output.stat().st_size


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT / 'dist/submission.zip')
    args = parser.parse_args()
    count, size = package(args.out)
    print(f'{args.out}: {count} files, {size:,} bytes; marketplace.json at ZIP root')
