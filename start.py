from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"

from project_cleanup import cleanup_legacy_runtime_files

cleanup_legacy_runtime_files(PROJECT_ROOT)

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


def configure_utf8_stdio() -> None:
    for stream in (
        sys.stdin,
        sys.stdout,
        sys.stderr,
    ):
        reconfigure = getattr(
            stream,
            "reconfigure",
            None,
        )
        if reconfigure is not None:
            reconfigure(
                encoding="utf-8",
                errors="replace",
            )


configure_utf8_stdio()


def check_dependencies() -> None:
    missing = []

    try:
        import yaml  # noqa: F401
    except ImportError:
        missing.append("PyYAML")

    try:
        import dotenv  # noqa: F401
    except ImportError:
        missing.append("python-dotenv")

    if missing:
        print(
            "缺少本地依赖："
            + ", ".join(missing)
        )
        raise SystemExit(2)


def main() -> None:
    check_dependencies()

    from task_closed_loop.app.runtime import main as runtime_main
    from task_closed_loop.app.runner import run

    run(runtime_main)


if __name__ == "__main__":
    main()
