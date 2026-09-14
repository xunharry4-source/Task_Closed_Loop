from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import sys
import traceback
from pathlib import Path


def _prepend_module_roots(values: list[str]) -> None:
    """Add trusted Host-selected module roots for isolated capability imports.

    ``python -I`` intentionally removes cwd/user-site influence.  Stage 2, however,
    is a persistent multi-file project (analysis/resources, analysis/functions,
    connectors).  The Host therefore passes the exact roots that generated code may
    import from.  Generated code cannot add arbitrary Host paths through this CLI.
    """

    roots: list[str] = []
    for raw in values:
        resolved = str(Path(raw).resolve())
        if resolved not in roots:
            roots.append(resolved)
    # Preserve caller order while putting the first declared root first.
    for root in reversed(roots):
        if root not in sys.path:
            sys.path.insert(0, root)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--entrypoint", required=True)
    parser.add_argument("--function", required=True)
    parser.add_argument("--module-root", action="append", default=[])
    args = parser.parse_args()
    payload = json.load(sys.stdin)
    entrypoint = Path(args.entrypoint).resolve()
    stdout_buffer = io.StringIO()
    stderr_buffer = io.StringIO()
    try:
        _prepend_module_roots(list(args.module_root or []))
        spec = importlib.util.spec_from_file_location("execution_capability", entrypoint)
        if not spec or not spec.loader:
            raise RuntimeError("unable to load capability module")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        function = getattr(module, args.function, None)
        if not callable(function):
            raise RuntimeError(f"entrypoint function not callable: {args.function}")
        with contextlib.redirect_stdout(stdout_buffer), contextlib.redirect_stderr(stderr_buffer):
            result = function(dict(payload.get("inputs", {})), dict(payload.get("context", {})))
        if not isinstance(result, dict):
            raise TypeError("capability execute() must return a dict")
        print(json.dumps({
            "ok": True,
            "result": result,
            "captured_stdout": stdout_buffer.getvalue(),
            "captured_stderr": stderr_buffer.getvalue(),
        }, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({
            "ok": False,
            "error": str(exc),
            "traceback": traceback.format_exc(limit=6),
            "captured_stdout": stdout_buffer.getvalue(),
            "captured_stderr": stderr_buffer.getvalue(),
        }, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
