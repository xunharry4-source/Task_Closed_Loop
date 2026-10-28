"""统一入口（Host 拥有，不要修改本文件）。

两种触发方式，走的是同一套代码：

1. Host 调用 `run(inputs, context)`（第二步自动初始化时）；
2. 手动触发，在 cli_project/ 下执行：

       python analysis/main.py --list
       python analysis/main.py --directory /path/to/data --write
       python analysis/main.py --function codex --write
       python analysis/main.py --inputs inputs.json --all --write

   `--write` 把结果合并进 generated/resources.generated.yml 与
   generated/capabilities.generated.yml（按 id 覆盖同名条目，其余保留）。

分析实现放在这里，由 CLI 生成或人工编写：

    analysis/resources/<资源id>.py   实现 analyze(target, context) -> dict
    analysis/functions/<功能名>.py    实现 analyze(target, context) -> dict

`target` 是该单元的配置（资源：{"id","kind","directory"}；功能：{"id"}），
返回值用 analysis/templates.py 里的 `resource()` / `capability()` 构造。
缺少实现时本入口会返回 availability=failed 的条目，绝不静默漏掉已配置的输入。
"""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
from pathlib import Path
import re
import sys
from typing import Any

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
for candidate in (str(HERE), str(PROJECT_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

import templates  # noqa: E402  (analysis/templates.py)

RESOURCE_DIR = HERE / "resources"
FUNCTION_DIR = HERE / "functions"
GENERATED_DIR = PROJECT_ROOT / "generated"
RESOURCES_FILE = GENERATED_DIR / "resources.generated.yml"
CAPABILITIES_FILE = GENERATED_DIR / "capabilities.generated.yml"


def resource_id_for_directory(directory: Path) -> str:
    """与 Host 的 id 规则保持一致：目录名归一化。"""

    cleaned = re.sub(r"[^0-9A-Za-z一-鿿]+", "_", directory.name).strip("_")
    return cleaned or "resource"


def _load_analyzer(directory: Path, unit_id: str):
    module_path = directory / f"{unit_id}.py"
    if not module_path.is_file():
        return None
    spec = importlib.util.spec_from_file_location(f"analysis_unit_{unit_id}", module_path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, "analyze", None)


def analyze_resource(target: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
    unit_id = str(target.get("id") or "").strip()
    analyze = _load_analyzer(RESOURCE_DIR, unit_id)
    if analyze is None:
        return templates.failed_resource(
            id=unit_id,
            type=str(target.get("kind") or "local_directory"),
            error=f"缺少分析实现 analysis/resources/{unit_id}.py",
        )
    try:
        return analyze(target, context or {})
    except Exception as exc:  # 一个单元失败不影响其它单元
        return templates.failed_resource(
            id=unit_id,
            type=str(target.get("kind") or "local_directory"),
            error=f"{type(exc).__name__}: {exc}",
        )


def analyze_function(target: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
    unit_id = str(target.get("id") or "").strip()
    analyze = _load_analyzer(FUNCTION_DIR, unit_id)
    if analyze is None:
        return templates.failed_capability(
            id=unit_id, error=f"缺少分析实现 analysis/functions/{unit_id}.py"
        )
    try:
        return analyze(target, context or {})
    except Exception as exc:
        return templates.failed_capability(id=unit_id, error=f"{type(exc).__name__}: {exc}")


def run(inputs: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
    """Host 契约：按配置逐个分析，返回两段填好的模版。"""

    inputs = inputs or {}
    resources: list[dict[str, Any]] = []
    capabilities: list[dict[str, Any]] = []

    for target in inputs.get("local_resources") or []:
        resources.append(analyze_resource(target, context))
    for target in inputs.get("remote_resources") or []:
        resources.append(analyze_resource(target, context))
    for target in inputs.get("functions") or []:
        capabilities.append(analyze_function(target, context))

    return {"resources": resources, "capabilities": capabilities}


# --- 手动触发 -----------------------------------------------------------------


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        import yaml

        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _dump_yaml(path: Path, payload: dict[str, Any]) -> None:
    import yaml

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )


def merge_into_generated(result: dict[str, Any]) -> list[Path]:
    """把结果按 id 合并进指定目录，已有的同名条目被替换，其它保留。"""

    written: list[Path] = []
    for path, key, producer, items in (
        (RESOURCES_FILE, "resources", "preflight.resource_analysis", result.get("resources") or []),
        (CAPABILITIES_FILE, "capabilities", "preflight.capability_analysis", result.get("capabilities") or []),
    ):
        if not items:
            continue
        document = _load_yaml(path)
        existing = [item for item in (document.get(key) or []) if isinstance(item, dict)]
        by_id = {str(item.get("id")): item for item in existing}
        for item in items:
            by_id[str(item.get("id"))] = item
        document.update(
            {
                "schema_version": document.get("schema_version") or "1.0",
                "producer": document.get("producer") or producer,
                key: list(by_id.values()),
            }
        )
        _dump_yaml(path, document)
        written.append(path)
    return written


def _units_from_args(args) -> dict[str, Any]:
    if args.inputs:
        raw = Path(args.inputs).read_text(encoding="utf-8")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            import yaml

            payload = yaml.safe_load(raw) or {}
        inputs = payload.get("inputs") if isinstance(payload.get("inputs"), dict) else payload
    else:
        inputs = {"local_resources": [], "remote_resources": [], "functions": []}

    for directory in args.directory or []:
        path = Path(directory).expanduser().resolve()
        inputs.setdefault("local_resources", []).append(
            {"id": resource_id_for_directory(path), "kind": "local_directory", "directory": str(path)}
        )
    for name in args.function or []:
        inputs.setdefault("functions", []).append({"id": name})

    if not args.all and (args.directory or args.function):
        # 只跑命令行上明确给的单元
        if args.directory:
            inputs["local_resources"] = [
                item
                for item in inputs.get("local_resources", [])
                if str(item.get("directory") or "")
                in {str(Path(d).expanduser().resolve()) for d in args.directory}
            ]
            inputs["remote_resources"] = []
        if args.function:
            inputs["functions"] = [
                item for item in inputs.get("functions", []) if item.get("id") in set(args.function)
            ]
    return inputs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="手动触发资源与功能分析")
    parser.add_argument("--inputs", help="JSON/YAML 文件，内容与 Host 传入的 inputs 相同")
    parser.add_argument("--directory", action="append", help="手动指定一个工作目录（可重复）")
    parser.add_argument("--function", action="append", help="手动指定一个功能名（可重复）")
    parser.add_argument("--all", action="store_true", help="分析 --inputs 里的全部单元")
    parser.add_argument("--write", action="store_true", help="把结果合并进 generated/")
    parser.add_argument("--list", action="store_true", help="列出已有的分析实现")
    args = parser.parse_args(argv)

    if args.list:
        print("资源分析实现：", sorted(p.stem for p in RESOURCE_DIR.glob("*.py")))
        print("功能分析实现：", sorted(p.stem for p in FUNCTION_DIR.glob("*.py")))
        return 0

    inputs = _units_from_args(args)
    if not any(inputs.get(key) for key in ("local_resources", "remote_resources", "functions")):
        parser.error("没有要分析的单元：用 --directory / --function / --inputs 指定")

    result = run(inputs, {"trigger": "manual"})
    if args.write:
        for path in merge_into_generated(result):
            print(f"已写入 {path}")
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
