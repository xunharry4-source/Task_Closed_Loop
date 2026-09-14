from __future__ import annotations

import hashlib
from pathlib import Path

from .errors import BuildError


def reject_symlinks(root: Path) -> None:
    for path in root.rglob("*"):
        if path.is_symlink():
            raise BuildError(f"symlinks are not allowed in candidate builds: {path}")


def candidate_checksum(build_path: Path) -> str:
    digest = hashlib.sha256()
    roots = [build_path / "implementation", build_path / "tests"]
    files = [build_path / "candidate_manifest.yml"]
    for root in roots:
        if root.exists():
            reject_symlinks(root)
            files.extend(sorted(p for p in root.rglob("*") if p.is_file() and "__pycache__" not in p.parts))
    for path in sorted(set(files), key=lambda p: p.relative_to(build_path).as_posix()):
        if not path.exists():
            continue
        digest.update(path.relative_to(build_path).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()
