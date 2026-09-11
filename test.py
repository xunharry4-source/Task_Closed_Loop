from __future__ import annotations

import sys
import unittest
from pathlib import Path

def configure_utf8_stdio() -> None:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


configure_utf8_stdio()

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"
TESTS_DIR = PROJECT_ROOT / "tests"

from project_cleanup import cleanup_legacy_runtime_files

cleanup_legacy_runtime_files(PROJECT_ROOT)

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))


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
        print("缺少本地依赖：" + ", ".join(missing))
        print("项目不会自动安装依赖，请使用你当前本地 Python 环境自行准备。")
        raise SystemExit(2)


def main() -> None:
    check_dependencies()

    suite = unittest.defaultTestLoader.discover(
        str(TESTS_DIR),
        pattern="test*.py",
    )

    result = unittest.TextTestRunner(
        verbosity=2,
    ).run(suite)

    raise SystemExit(
        0 if result.wasSuccessful() else 1
    )


if __name__ == "__main__":
    main()
