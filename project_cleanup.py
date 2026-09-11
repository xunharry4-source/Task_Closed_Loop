from __future__ import annotations

from pathlib import Path
import shutil


LEGACY_RUNTIME_FILES = (
    "src/task_closed_loop/llm/fake.py",
    "src/task_closed_loop/llm/mock.py",
    "src/task_closed_loop/adapters/fake_scenarios.py",
)


def cleanup_legacy_runtime_files(
    project_root: str | Path,
) -> list[str]:
    """
    Remove runtime files that existed in old project releases
    but are no longer part of the current architecture.

    This is intentionally narrow: only fixed, known legacy
    paths are removed.
    """
    root = Path(project_root)
    removed: list[str] = []

    for relative in LEGACY_RUNTIME_FILES:
        path = root / relative

        if path.exists() and path.is_file():
            path.unlink()
            removed.append(relative)

        cache_dir = path.parent / "__pycache__"
        if cache_dir.exists():
            # Old bytecode can preserve removed runtime modules.
            shutil.rmtree(
                cache_dir,
                ignore_errors=True,
            )

    return removed
