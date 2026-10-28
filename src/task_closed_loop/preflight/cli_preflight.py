"""Locked Stage 2: CLI-authored Resource & Function analysis.

The CLI works directly inside the persistent ``cli_project/``. It creates and keeps
analysis/connector code there, inspects configured local resource directories and
remote resource scopes, exercises configured functions when possible, and returns a
strict analysis payload. The Host writes both human/diagnostic analysis files and the
two standard Task-layer input files.

Nothing in this module creates business Tasks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Iterable, Sequence

import yaml

from task_closed_loop.capability_runtime import capability_runner
from task_closed_loop.capability_runtime.cli.base import CliEngineAdapter
from task_closed_loop.capability_runtime.cli.claude import ClaudeCliAdapter
from task_closed_loop.capability_runtime.cli.codex import CodexCliAdapter
from task_closed_loop.capability_runtime.cli.gemini import GeminiCliAdapter
from task_closed_loop.capability_runtime.cli.router import CliEngineRouter
from task_closed_loop.capability_runtime.errors import CliEngineError
from task_closed_loop.capability_runtime.secrets import DotEnvSecretResolver
from task_closed_loop.diagnostics.logging import runtime_logger

from .models import PreflightCapabilityRecord, PreflightResourceRecord
from .writer import write_preflight_files


class PreflightSourceConfigurationError(ValueError):
    """Stage 2 input configuration is missing, malformed, or violates the lock."""


class PreflightAnalysisError(RuntimeError):
    """The CLI Project could not produce the locked Stage 2 outputs."""


ANALYSIS_ENTRYPOINT = "main.py"
ANALYSIS_FUNCTION = "run"

_FORBIDDEN_KEYS = {
    "password",
    "secret",
    "token",
    "credential",
    "credentials",
    "dsn",
    "connection_string",
    "api_key",
    "access_token",
    "refresh_token",
}


def _assert_no_inline_secret(value: Any, *, where: str) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).strip().lower()
            if normalized in _FORBIDDEN_KEYS:
                raise PreflightSourceConfigurationError(
                    f"{where} 不允许内联凭据字段 '{key}'；真实值必须放在 cli_project/.env，配置只写 secret_refs。"
                )
            _assert_no_inline_secret(item, where=f"{where}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _assert_no_inline_secret(item, where=f"{where}[{index}]")


@dataclass(frozen=True)
class LocalResourceInput:
    """A configured working directory. The user writes the path, nothing else."""

    input_id: str
    directory: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {
            "id": self.input_id,
            "kind": "local_directory",
            "directory": self.directory,
        }


@dataclass(frozen=True)
class RemoteResourceInput:
    """A remote scope reached through a function.

    Kept as an internal section (the architecture lock names it) but no longer part of
    what the user configures: a function is just a name, and whatever it exposes is
    discovered by the analysis.
    """

    input_id: str
    kind: str = ""
    function_id: str = ""
    scope: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {
            "id": self.input_id,
            "kind": self.kind,
            "function_id": self.function_id,
            "scope": dict(self.scope),
        }


@dataclass(frozen=True)
class FunctionInput:
    """A configured function. The user writes its name, nothing else.

    No operations whitelist, no scope, no secret_refs, no kind: what the function is
    and what it can do is not ours to declare. Credentials stay in `cli_project/.env`.
    """

    function_id: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {"id": self.function_id}


@dataclass(frozen=True)
class PreflightInputBundle:
    local_resources: tuple[LocalResourceInput, ...] = ()
    remote_resources: tuple[RemoteResourceInput, ...] = ()
    functions: tuple[FunctionInput, ...] = ()

    @property
    def total_count(self) -> int:
        return len(self.local_resources) + len(self.remote_resources) + len(self.functions)

    def to_payload(self) -> dict[str, Any]:
        return {
            "local_resources": [item.to_payload() for item in self.local_resources],
            "remote_resources": [item.to_payload() for item in self.remote_resources],
            "functions": [item.to_payload() for item in self.functions],
        }


@dataclass(frozen=True)
class Stage2MaterializationOutput:
    resources_path: Path
    capabilities_path: Path
    resource_analysis_path: Path
    function_analysis_path: Path
    cli_engine: str


# Legacy shape retained only as a Python compatibility object for old external code.
# The formal runtime no longer accepts preflight_sources.sources.
@dataclass(frozen=True)
class PreflightSource:
    source_id: str
    kind: str
    description: str = ""
    secret_refs: tuple[str, ...] = ()
    operations: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {
            "id": self.source_id,
            "kind": self.kind,
            "description": self.description,
            "secret_refs": list(self.secret_refs),
            "operations": list(self.operations),
            "metadata": dict(self.metadata),
        }



def _cli_progress_reporter(label: str):
    """Report what the CLI is actually doing, one readable line at a time.

    `codex exec --json` emits an event per line and carries the detail in a nested
    `item`. Only events that say something about the work are reported: running a
    command, writing a file, what the agent said, and errors. Lifecycle chatter
    (`item.started`, `turn.started`, ...) is dropped so the signal stays visible.
    """

    logger = runtime_logger()

    def report(stream: str, line: str) -> None:
        text = line.strip()
        if not text:
            return

        if not text.startswith("{"):
            logger.info("stage2.cli[%s] %s", label, text[:200])
            return

        try:
            event = json.loads(text)
        except json.JSONDecodeError:
            return
        if not isinstance(event, dict):
            return

        # Only completed work carries a result worth showing.
        if str(event.get("type") or "") != "item.completed":
            return
        item = event.get("item")
        if not isinstance(item, dict):
            return

        kind = str(item.get("type") or "").strip()
        if kind == "command_execution":
            command = str(item.get("command") or "").strip()
            exit_code = item.get("exit_code")
            detail = f"$ {command}"
            if exit_code not in (None, 0):
                detail += f"  (exit={exit_code})"
        elif kind in {"agent_message", "reasoning"}:
            detail = " ".join(str(item.get("text") or "").split())
        elif kind == "error":
            detail = "ERROR " + " ".join(str(item.get("message") or "").split())
        elif kind in {"file_change", "patch_apply"}:
            changed = item.get("path") or item.get("files") or item.get("changes")
            detail = f"写入 {changed}"
        else:
            return

        detail = detail.strip()
        if not detail:
            return
        if len(detail) > 180:
            detail = detail[:180] + "…"
        logger.info("stage2.cli[%s] %s", label, detail)

    return report


def resource_id_for_directory(directory: Path, *, taken: set[str]) -> str:
    """A stable id derived from the path: the directory name, parent-qualified on clash.

    It has to be stable across runs (references are written `resource:<id>`, and the
    task store keys history by it), so it is derived from the path alone — never from
    anything a model wrote.
    """

    def normalize(text: str) -> str:
        cleaned = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "_", str(text)).strip("_")
        return cleaned or "resource"

    name = normalize(directory.name)
    if name not in taken:
        return name
    parent = normalize(directory.parent.name)
    qualified = f"{parent}_{name}" if parent else name
    if qualified not in taken:
        return qualified
    index = 2
    while f"{qualified}_{index}" in taken:
        index += 1
    return f"{qualified}_{index}"


_AVAILABILITY = ("available", "unavailable", "failed")

ANALYZE_AUTO = "auto"
ANALYZE_ALWAYS = "always"
ANALYZE_NEVER = "never"


def analysis_mode(config: dict) -> str:
    """Step 2 initializes the data; it does not have to run every time.

    - `auto` (default): run only when the saved templates are missing or empty.
    - `always` / true: re-initialize this run.
    - `never` / false: never run; use what is saved (error if nothing is saved).
    """

    section = (config or {}).get("preflight_inputs") or {}
    raw = section.get("analyze", ANALYZE_AUTO)
    if isinstance(raw, bool):
        return ANALYZE_ALWAYS if raw else ANALYZE_NEVER
    name = str(raw or "").strip().lower()
    if name in {ANALYZE_ALWAYS, "true", "yes", "on", "refresh"}:
        return ANALYZE_ALWAYS
    if name in {ANALYZE_NEVER, "false", "no", "off", "skip"}:
        return ANALYZE_NEVER
    return ANALYZE_AUTO


def load_preflight_inputs(config: dict, *, project_root: str | Path) -> PreflightInputBundle:
    """Load the first step's configuration: directories, functions, CLI.

    Accepted shape:

        preflight_inputs:
          cli: codex
          directories: [/path/one, /path/two]
          functions: [codex, gmail]

    Ids are derived from the paths and the function names, so there is nothing else to
    fill in. The older per-item mapping form (`local_resources: [{id, directory}]`,
    `functions: [{id: ...}]`) is still accepted so existing configs keep working.
    """

    if "preflight_sources" in (config or {}):
        raise PreflightSourceConfigurationError(
            "已废弃 preflight_sources.sources 单列表。请使用 preflight_inputs 的 directories / functions / cli。"
        )

    section = (config or {}).get("preflight_inputs") or {}
    if not section.get("enabled", True):
        return PreflightInputBundle()

    root = Path(project_root).resolve()
    directories_raw = section.get("directories")
    if directories_raw is None:
        directories_raw = section.get("local_resources") or []
    functions_raw = section.get("functions") or []
    remote_raw = section.get("remote_resources") or []
    for name, values in (
        ("directories", directories_raw),
        ("functions", functions_raw),
        ("remote_resources", remote_raw),
    ):
        if not isinstance(values, list):
            raise PreflightSourceConfigurationError(f"preflight_inputs.{name} 必须是列表。")

    local: list[LocalResourceInput] = []
    taken: set[str] = set()
    for index, item in enumerate(directories_raw, start=1):
        if isinstance(item, dict):
            _assert_no_inline_secret(item, where=f"directories[{index}]")
            directory = str(item.get("directory") or item.get("path") or "").strip()
            explicit_id = str(item.get("id") or "").strip()
        else:
            directory = str(item or "").strip()
            explicit_id = ""
        if not directory:
            raise PreflightSourceConfigurationError(f"directories[{index}] 没有写路径。")
        path = Path(directory).expanduser()
        resolved = (path if path.is_absolute() else (root / path)).resolve()
        if not resolved.is_dir():
            raise PreflightSourceConfigurationError(
                f"配置的工作目录不存在或不是目录：{resolved}"
            )
        input_id = explicit_id or resource_id_for_directory(resolved, taken=taken)
        if input_id in taken:
            raise PreflightSourceConfigurationError(f"Stage 2 输入 id 重复：{input_id}")
        taken.add(input_id)
        local.append(LocalResourceInput(input_id=input_id, directory=str(resolved)))

    functions: list[FunctionInput] = []
    for index, item in enumerate(functions_raw, start=1):
        if isinstance(item, dict):
            _assert_no_inline_secret(item, where=f"functions[{index}]")
            function_id = str(item.get("id") or item.get("name") or "").strip()
        else:
            function_id = str(item or "").strip()
        if not function_id:
            raise PreflightSourceConfigurationError(f"functions[{index}] 没有写功能名。")
        if function_id in taken:
            raise PreflightSourceConfigurationError(f"Stage 2 输入 id 重复：{function_id}")
        taken.add(function_id)
        functions.append(FunctionInput(function_id=function_id))

    function_ids = {item.function_id for item in functions}
    remote: list[RemoteResourceInput] = []
    for index, item in enumerate(remote_raw, start=1):
        if not isinstance(item, dict):
            raise PreflightSourceConfigurationError(f"remote_resources[{index}] 必须是映射。")
        _assert_no_inline_secret(item, where=f"remote_resources[{index}]")
        input_id = str(item.get("id") or "").strip()
        function_id = str(item.get("function_id") or "").strip()
        if not input_id:
            raise PreflightSourceConfigurationError(f"remote_resources[{index}] 缺少 id。")
        if function_id and function_id not in function_ids:
            raise PreflightSourceConfigurationError(
                f"remote resource '{input_id}' 引用未配置的功能：{function_id}"
            )
        if input_id in taken:
            raise PreflightSourceConfigurationError(f"Stage 2 输入 id 重复：{input_id}")
        taken.add(input_id)
        remote.append(
            RemoteResourceInput(
                input_id=input_id,
                kind=str(item.get("kind") or "").strip(),
                function_id=function_id,
                scope=dict(item.get("scope") or {}),
            )
        )

    return PreflightInputBundle(tuple(local), tuple(remote), tuple(functions))


def load_preflight_sources(config: dict) -> list[PreflightSource]:
    """Deprecated compatibility parser; formal runtime never calls this in V1.1."""
    section = (config or {}).get("preflight_sources") or {}
    raw_sources = section.get("sources") or []
    out: list[PreflightSource] = []
    for index, item in enumerate(raw_sources, start=1):
        if not isinstance(item, dict):
            raise PreflightSourceConfigurationError(f"preflight_sources.sources[{index}] 必须是映射。")
        _assert_no_inline_secret(item, where=f"preflight_sources.sources[{index}]")
        source_id = _unique_id(item, section="preflight_sources.sources", index=index)
        kind = str(item.get("kind") or "").strip()
        if not kind:
            raise PreflightSourceConfigurationError(f"preflight source '{source_id}' 缺少 kind。")
        out.append(
            PreflightSource(
                source_id=source_id,
                kind=kind,
                description=str(item.get("description") or "").strip(),
                secret_refs=tuple(str(v).strip() for v in (item.get("secret_refs") or []) if str(v).strip()),
                operations=tuple(str(v).strip() for v in (item.get("operations") or []) if str(v).strip()),
                metadata=dict(item.get("metadata") or {}),
            )
        )
    return out


def default_cli_adapters() -> list[CliEngineAdapter]:
    return [CodexCliAdapter(), GeminiCliAdapter(), ClaudeCliAdapter()]


def render_source_analysis_prompt(
    *,
    prompt_text: str,
    sources: Sequence[PreflightSource] | None = None,
    inputs: PreflightInputBundle | None = None,
    has_existing_code: bool,
) -> str:
    if inputs is None:
        payload: Any = {"legacy_sources": [s.to_payload() for s in (sources or [])]}
    else:
        payload = inputs.to_payload()
    state = (
        "cli_project/analysis/main.py 已存在；必须在现有代码基础上增量更新。"
        if has_existing_code
        else "cli_project/analysis/main.py 尚不存在；请按固定架构创建分析代码。"
    )
    return (
        f"{prompt_text}\n\n"
        "## 本轮固定 Stage 2 输入\n\n"
        f"```json\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n```\n\n"
        f"## 当前状态\n\n{state}\n"
    )


class CliPreflightEngine:
    """Stage 2 driver: CLI authors code in-place, Host runs/validates its analysis."""

    def __init__(
        self,
        *,
        project_root: Path,
        prompt_text: str,
        adapters: Iterable[CliEngineAdapter] | None = None,
        preferred_engines: Sequence[str] | None = None,
        secret_resolver=None,
    ):
        self.project_root = Path(project_root).resolve()
        self.prompt_text = prompt_text
        self.router = CliEngineRouter(
            adapters if adapters is not None else default_cli_adapters(),
            preferred=list(preferred_engines) if preferred_engines else None,
        )
        self.secret_resolver = secret_resolver or DotEnvSecretResolver(self.project_root / ".env")

    @property
    def analysis_dir(self) -> Path:
        return self.project_root / "analysis"

    @property
    def generated_dir(self) -> Path:
        return self.project_root / "generated"

    @property
    def entrypoint(self) -> Path:
        return self.analysis_dir / ANALYSIS_ENTRYPOINT

    @property
    def receipt_path(self) -> Path:
        """One Host-written receipt replaces the two CLI-authored analysis files."""

        return self.analysis_dir / "results" / "stage2.analysis.yml"

    # The contract DTO still carries two analysis paths; both name the receipt, so
    # `contracts/` and `pipeline/production.py` stay untouched.
    @property
    def resource_analysis_path(self) -> Path:
        return self.receipt_path

    @property
    def function_analysis_path(self) -> Path:
        return self.receipt_path

    def has_analysis_code(self) -> bool:
        return self.entrypoint.is_file()

    def build_analysis_code(
        self,
        inputs: PreflightInputBundle | Sequence[PreflightSource],
        *,
        explicit_engine: str | None = None,
        progress_label: str | None = None,
    ) -> str:
        """Call the CLI directly in the persistent cli_project and keep its code there."""

        bundle = inputs if isinstance(inputs, PreflightInputBundle) else None
        legacy = None if bundle is not None else list(inputs)
        prompt = render_source_analysis_prompt(
            prompt_text=self.prompt_text,
            inputs=bundle,
            sources=legacy,
            has_existing_code=self.has_analysis_code(),
        )
        ready = self.router.ready_candidates(explicit_engine)
        if not ready:
            self.router.select(explicit_engine)
            raise AssertionError("unreachable")
        failures: list[str] = []
        for adapter in ready:
            try:
                result = adapter.run(
                    mode="build",
                    prompt=prompt,
                    cwd=self.project_root,
                    # Stage 2 has no time limit: analyzing a real system takes as
                    # long as it takes, and a killed run produces nothing usable.
                    timeout_seconds=None,
                    on_output=_cli_progress_reporter(progress_label or adapter.engine_id),
                )
            except Exception as exc:
                failures.append(f"{adapter.engine_id}: {type(exc).__name__}: {exc}")
                if explicit_engine:
                    break
                continue
            if result.succeeded and self.entrypoint.is_file():
                return adapter.engine_id
            failures.append(
                f"{adapter.engine_id}: exit={result.exit_code}; "
                f"entrypoint={self.entrypoint.is_file()}; stderr={result.stderr[-1000:]}"
            )
            if explicit_engine:
                break
        raise PreflightAnalysisError(
            "Stage 2 CLI 分析代码生成失败；READY CLI 尝试结果：" + " | ".join(failures)
        )

    def run_analysis(self, inputs: PreflightInputBundle) -> dict[str, Any]:
        if not self.has_analysis_code():
            raise PreflightAnalysisError(f"CLI Project 缺少分析代码入口：{self.entrypoint}")

        secrets = self.secret_resolver.resolve(inputs.secret_refs) if inputs.secret_refs else {}
        artifact_dir = self.project_root / "artifacts" / "preflight"
        temp_dir = self.project_root / "temp" / "preflight"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        temp_dir.mkdir(parents=True, exist_ok=True)

        runner = Path(capability_runner.__file__).resolve()
        command = [
            sys.executable,
            "-I",
            str(runner),
            "--entrypoint",
            str(self.entrypoint.resolve()),
            "--function",
            ANALYSIS_FUNCTION,
            "--module-root",
            str(self.analysis_dir.resolve()),
            "--module-root",
            str(self.project_root.resolve()),
        ]
        env = {
            "PATH": os.environ.get("PATH", ""),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONIOENCODING": "utf-8",
            "EXECUTION_PROJECT_CAPABILITY_MODE": "1",
        }
        payload = json.dumps(
            {
                "inputs": inputs.to_payload(),
                "context": {
                    "secrets": secrets,
                    "artifact_dir": str(artifact_dir),
                    "temp_dir": str(temp_dir),
                    "generated_dir": str(self.generated_dir),
                    "analysis_results_dir": str(self.analysis_dir / "results"),
                },
            },
            ensure_ascii=False,
        )
        # No time limit: analyzing a real system takes as long as it takes, and a
        # killed run produces nothing usable.
        proc = subprocess.run(
            command,
            input=payload,
            cwd=str(self.analysis_dir),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        try:
            message = json.loads(proc.stdout.strip() or "{}")
        except Exception as exc:
            raise PreflightAnalysisError(
                "Stage 2 分析代码没有返回合法 JSON："
                f"exit={proc.returncode} stdout={proc.stdout[-1000:]!r} stderr={proc.stderr[-1000:]!r}"
            ) from exc
        if proc.returncode != 0 or not message.get("ok"):
            raise PreflightAnalysisError(
                "Stage 2 分析代码执行失败：" + str(message.get("error") or proc.stderr or "unknown error")
            )
        raw = message.get("result")
        if not isinstance(raw, dict):
            raise PreflightAnalysisError(f"analysis/{ANALYSIS_ENTRYPOINT} 的 {ANALYSIS_FUNCTION}() 必须返回 dict。")
        return raw

    @staticmethod
    def _local_tree_receipt(item: LocalResourceInput) -> dict[str, Any]:
        root = Path(item.directory).resolve()
        files: list[dict[str, Any]] = []
        dir_count = 0
        for path in sorted(root.rglob("*"), key=lambda value: value.as_posix()):
            if path.is_dir():
                dir_count += 1
                continue
            if not path.is_file():
                continue
            stat = path.stat()
            files.append({
                "relative_path": path.relative_to(root).as_posix(),
                "size": int(stat.st_size),
            })
        digest_source = json.dumps(files, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(digest_source.encode("utf-8")).hexdigest()
        return {
            "evidence_id": f"host-local:{item.input_id}:{digest[:16]}",
            "source_type": "local_resource",
            "source_id": item.input_id,
            "operation": "filesystem_scan",
            "status": "success",
            "observed_via": "host_filesystem_scan",
            "raw_observation": {
                "file_count": len(files),
                "directory_count": dir_count,
                "tree_digest": digest,
                "files": files,
            },
        }
    def _validate_unit_output(self, raw: Any, inputs: PreflightInputBundle) -> None:
        """One template, four checks.

        Coverage, explicit availability, real lineage ids, and a `summary` on every
        resource. Everything the old two-template gate demanded on top of that
        (structured evidence, implementation_files, an operations whitelist,
        per-operation capabilities, and a consistency cross-check between two
        CLI-authored shapes) is gone: none of it had a downstream consumer, and the
        cross-check turned a successful probe into a failed unit.
        """

        if not isinstance(raw, dict):
            raise PreflightAnalysisError("Stage 2 返回必须是 object。")

        resources = raw.get("resources") or []
        capabilities = raw.get("capabilities") or []
        if not isinstance(resources, list) or not isinstance(capabilities, list):
            raise PreflightAnalysisError("Stage 2 的 resources / capabilities 必须是列表。")

        configured_resource_ids = {item.input_id for item in inputs.local_resources} | {
            item.input_id for item in inputs.remote_resources
        }
        configured_function_ids = {item.function_id for item in inputs.functions}

        covered_inputs: set[str] = set()
        for index, item in enumerate(resources, start=1):
            if not isinstance(item, dict):
                raise PreflightAnalysisError(f"Stage 2 resources[{index}] 必须是映射。")
            resource_id = str(item.get("id") or "").strip()
            if not resource_id:
                raise PreflightAnalysisError(f"Stage 2 resources[{index}] 缺少 id。")
            if not str(item.get("summary") or "").strip():
                raise PreflightAnalysisError(
                    f"Stage 2 resource '{resource_id}' 缺少 summary："
                    "用一句话说明这是什么、现在有什么、到什么程度。"
                )
            self._require_availability(
                item.get("availability"), label=f"resource '{resource_id}'"
            )
            sources = (item.get("metadata") or {}).get("source_input_ids")
            if not isinstance(sources, list) or not sources:
                raise PreflightAnalysisError(
                    f"Stage 2 resource '{resource_id}' 缺少 metadata.source_input_ids。"
                )
            normalized = {str(value).strip() for value in sources if str(value).strip()}
            unknown = sorted(normalized - configured_resource_ids)
            if unknown:
                raise PreflightAnalysisError(
                    f"Stage 2 resource '{resource_id}' 引用了未配置的来源：{unknown}"
                )
            covered_inputs |= normalized

        covered_functions: set[str] = set()
        for index, item in enumerate(capabilities, start=1):
            if not isinstance(item, dict):
                raise PreflightAnalysisError(f"Stage 2 capabilities[{index}] 必须是映射。")
            capability_id = str(item.get("id") or "").strip()
            if not capability_id:
                raise PreflightAnalysisError(f"Stage 2 capabilities[{index}] 缺少 id。")
            self._require_availability(
                item.get("availability"), label=f"capability '{capability_id}'"
            )
            function_id = str(
                (item.get("metadata") or {}).get("source_function_id") or ""
            ).strip()
            if not function_id:
                raise PreflightAnalysisError(
                    f"Stage 2 capability '{capability_id}' 缺少 metadata.source_function_id。"
                )
            if function_id not in configured_function_ids:
                raise PreflightAnalysisError(
                    f"Stage 2 capability '{capability_id}' 引用了未配置的功能：{function_id}"
                )
            covered_functions.add(function_id)

        missing_inputs = sorted(configured_resource_ids - covered_inputs)
        if missing_inputs:
            raise PreflightAnalysisError(
                f"Stage 2 没有覆盖这些已配置的工作目录：{missing_inputs}"
            )
        missing_functions = sorted(configured_function_ids - covered_functions)
        if missing_functions:
            raise PreflightAnalysisError(
                f"Stage 2 没有覆盖这些已配置的功能：{missing_functions}"
            )

    @staticmethod
    def _require_availability(value: Any, *, label: str) -> str:
        availability = str(value or "").strip()
        if availability not in _AVAILABILITY:
            raise PreflightAnalysisError(
                f"Stage 2 {label} 的 availability 必须显式写成 "
                f"{' / '.join(_AVAILABILITY)}，当前是 {availability or '（空）'}。"
            )
        return availability

    def _write_receipt(
        self,
        *,
        units: list[tuple[str, PreflightInputBundle]],
        resources: list[dict[str, Any]],
        capabilities: list[dict[str, Any]],
        failures: list[tuple[str, str]],
        engine: str,
    ) -> Path:
        """What this run received — written by the Host, not by the CLI.

        This replaces the two CLI-authored analysis files: a receipt has no template to
        fill in wrong and nothing to cross-check against.
        """

        by_input: dict[str, dict[str, Any]] = {}
        for item in resources:
            for source in (item.get("metadata") or {}).get("source_input_ids") or []:
                entry = by_input.setdefault(
                    str(source), {"resources": [], "capabilities": []}
                )
                entry["resources"].append(str(item.get("id") or ""))
                entry["availability"] = str(item.get("availability") or "")
                entry["summary"] = str(item.get("summary") or "")
        for item in capabilities:
            function_id = str((item.get("metadata") or {}).get("source_function_id") or "")
            entry = by_input.setdefault(function_id, {"resources": [], "capabilities": []})
            entry["capabilities"].append(str(item.get("id") or ""))
            entry["availability"] = str(item.get("availability") or "")

        local_scans = {
            resource.input_id: self._local_tree_receipt(resource)
            for _, unit in units
            for resource in unit.local_resources
        }

        path = self.receipt_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            yaml.safe_dump(
                {
                    "schema_version": "2.0",
                    "producer": "preflight.stage2_receipt",
                    "engine": engine,
                    "inputs": by_input,
                    "host_local_scan": local_scans,
                    "failures": {label: message for label, message in failures},
                },
                allow_unicode=True,
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        return path

    @staticmethod
    def _split_units(
        inputs: PreflightInputBundle,
    ) -> list[tuple[str, PreflightInputBundle]]:
        """One analysis unit per configured input.

        A remote resource is validated against its function, so it travels in the
        same unit as the function it depends on. Everything else stands alone.
        """

        units: list[tuple[str, PreflightInputBundle]] = []

        for resource in inputs.local_resources:
            units.append(
                (
                    f"local_resource:{resource.input_id}",
                    PreflightInputBundle(local_resources=(resource,)),
                )
            )

        for function in inputs.functions:
            attached = tuple(
                remote
                for remote in inputs.remote_resources
                if remote.function_id == function.function_id
            )
            units.append(
                (
                    f"function:{function.function_id}",
                    PreflightInputBundle(functions=(function,), remote_resources=attached),
                )
            )

        orphan = tuple(
            remote
            for remote in inputs.remote_resources
            if not any(f.function_id == remote.function_id for f in inputs.functions)
        )
        for remote in orphan:
            units.append(
                (
                    f"remote_resource:{remote.input_id}",
                    PreflightInputBundle(remote_resources=(remote,)),
                )
            )

        return units

    @staticmethod
    def _failed_unit_entry(
        label: str,
        unit: PreflightInputBundle,
        message: str,
    ) -> tuple[str, dict[str, Any] | None]:
        """Record a failed unit so a configured input is never silently missing."""

        if unit.functions:
            function_id = unit.functions[0].function_id
            return (
                "capabilities",
                {
                    "id": function_id,
                    "availability": "failed",
                    "metadata": {"source_function_id": function_id, "host_error": message},
                },
            )
        if unit.local_resources or unit.remote_resources:
            source = (unit.local_resources or unit.remote_resources)[0]
            return (
                "resources",
                {
                    "id": source.input_id,
                    "type": "local_directory" if unit.local_resources else "remote_scope",
                    "summary": f"本轮分析失败，内容未知：{message}",
                    "availability": "failed",
                    "payload": {},
                    "metadata": {"source_input_ids": [source.input_id], "host_error": message},
                },
            )
        return ("resources", None)

    @property
    def _build_state_path(self) -> Path:
        return self.project_root / "state" / "stage2_build_state.yml"

    def _unit_fingerprint(self, unit: PreflightInputBundle) -> str:
        """Identity of what the CLI was last asked to build for this unit.

        Covers the unit's configuration and the prompt itself, so changing either
        forces the analysis code to be regenerated.
        """

        payload = json.dumps(
            {"inputs": unit.to_payload(), "prompt": self.prompt_text},
            ensure_ascii=False,
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _load_build_state(self) -> dict[str, Any]:
        path = self._build_state_path
        if not path.is_file():
            return {}
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            return {}
        units = data.get("units")
        return units if isinstance(units, dict) else {}

    def _save_build_state(self, state: dict[str, Any]) -> None:
        path = self._build_state_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            yaml.safe_dump(
                {"schema_version": "1.0", "units": state},
                allow_unicode=True,
                sort_keys=False,
            ),
            encoding="utf-8",
        )

    def _build_is_current(
        self,
        state: dict[str, Any],
        label: str,
        fingerprint: str,
    ) -> bool:
        """Whether the previously built code still matches this unit and is intact."""

        record = state.get(label)
        if not isinstance(record, dict):
            return False
        if str(record.get("fingerprint") or "") != fingerprint:
            return False
        if not self.has_analysis_code():
            return False
        # Every file the last successful analysis declared must still be present.
        for relative in record.get("implementation_files") or []:
            if not (self.project_root / str(relative)).is_file():
                return False
        return True

    # -- saved templates (step 2 is initialization; it need not run every time) ----

    def saved_templates(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]] | None:
        """What is already saved in the designated directory, or None if nothing is."""

        resources_path = self.generated_dir / "resources.generated.yml"
        capabilities_path = self.generated_dir / "capabilities.generated.yml"
        if not resources_path.exists() or not capabilities_path.exists():
            return None
        try:
            resources = (yaml.safe_load(resources_path.read_text(encoding="utf-8")) or {}).get(
                "resources"
            ) or []
            capabilities = (
                yaml.safe_load(capabilities_path.read_text(encoding="utf-8")) or {}
            ).get("capabilities") or []
        except (OSError, yaml.YAMLError):
            return None
        if not isinstance(resources, list) or not isinstance(capabilities, list):
            return None
        if not resources and not capabilities:
            return None
        return (
            [item for item in resources if isinstance(item, dict)],
            [item for item in capabilities if isinstance(item, dict)],
        )

    def saved_entries_for(
        self, unit: PreflightInputBundle
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]] | None:
        """The saved entries covering exactly this unit, or None if it is not covered."""

        saved = self.saved_templates()
        if saved is None:
            return None
        resources, capabilities = saved
        wanted_inputs = {item.input_id for item in unit.local_resources} | {
            item.input_id for item in unit.remote_resources
        }
        wanted_functions = {item.function_id for item in unit.functions}

        unit_resources = [
            item
            for item in resources
            if wanted_inputs
            & {
                str(value).strip()
                for value in (item.get("metadata") or {}).get("source_input_ids") or []
            }
        ]
        unit_capabilities = [
            item
            for item in capabilities
            if str((item.get("metadata") or {}).get("source_function_id") or "").strip()
            in wanted_functions
        ]
        covered_inputs = {
            str(value).strip()
            for item in unit_resources
            for value in (item.get("metadata") or {}).get("source_input_ids") or []
        }
        covered_functions = {
            str((item.get("metadata") or {}).get("source_function_id") or "").strip()
            for item in unit_capabilities
        }
        if wanted_inputs - covered_inputs or wanted_functions - covered_functions:
            return None
        return unit_resources, unit_capabilities

    def saved_covers(self, inputs: PreflightInputBundle) -> bool:
        """Do the saved templates already cover every configured input?

        This is what decides whether step 2 has to initialize anything: a new
        directory or function in the configuration means the saved data is incomplete.
        """

        saved = self.saved_templates()
        if saved is None:
            return False
        resources, capabilities = saved
        covered_inputs = {
            str(value).strip()
            for item in resources
            for value in (item.get("metadata") or {}).get("source_input_ids") or []
        }
        covered_functions = {
            str((item.get("metadata") or {}).get("source_function_id") or "").strip()
            for item in capabilities
        }
        configured_inputs = {item.input_id for item in inputs.local_resources} | {
            item.input_id for item in inputs.remote_resources
        }
        configured_functions = {item.function_id for item in inputs.functions}
        return configured_inputs <= covered_inputs and configured_functions <= covered_functions

    def reuse_saved(self, inputs: PreflightInputBundle) -> Stage2MaterializationOutput:
        """Use the saved templates as they are, without calling the CLI."""

        saved = self.saved_templates()
        if saved is None:
            raise PreflightSourceConfigurationError(
                f"第二步设为不执行，但 {self.generated_dir} 里没有已保存的资源/功能模版。"
                "先让它执行一次（analyze: always），或把已有模版放到该目录。"
            )
        resources, capabilities = saved
        missing_summary = [
            str(item.get("id") or "")
            for item in resources
            if not str(item.get("summary") or "").strip()
        ]
        if missing_summary:
            runtime_logger().warning(
                "stage2.reuse 已保存模版缺少 summary（后续只能看到 id 与类型）：%s",
                missing_summary,
            )
        self._write_receipt(
            units=self._split_units(inputs),
            resources=resources,
            capabilities=capabilities,
            failures=[],
            engine="reused_saved",
        )
        runtime_logger().info(
            "stage2.reuse 使用已保存模版 resources=%d capabilities=%d",
            len(resources),
            len(capabilities),
        )
        return Stage2MaterializationOutput(
            resources_path=self.generated_dir / "resources.generated.yml",
            capabilities_path=self.generated_dir / "capabilities.generated.yml",
            resource_analysis_path=self.receipt_path,
            function_analysis_path=self.receipt_path,
            cli_engine="reused_saved",
        )

    def materialize(
        self,
        inputs: PreflightInputBundle,
        *,
        explicit_engine: str | None = None,
        reuse_saved: bool = False,
    ) -> Stage2MaterializationOutput:
        if inputs.total_count == 0:
            raise PreflightSourceConfigurationError(
                "Stage 2 没有任何配置输入；必须至少配置 local_resources / remote_resources / functions 之一。"
            )

        # One unit at a time, one step at a time. A single unreachable function or
        # directory must not discard the analysis of everything else, and each
        # build/run/validate step is observable on its own.
        units = self._split_units(inputs)
        logger = runtime_logger()
        engine_id = ""
        aggregated: dict[str, list] = {"resources": [], "capabilities": []}
        unit_failures: list[tuple[str, str]] = []

        build_state = self._load_build_state()

        for position, (label, unit) in enumerate(units, start=1):
            logger.info("stage2.unit start %d/%d %s", position, len(units), label)

            # Step 2 initializes data. With `reuse_saved`, a unit that already has saved
            # data is skipped entirely; only what is missing gets initialized, so adding
            # one directory does not re-analyse everything — and does not go missing.
            if reuse_saved:
                saved_unit = self.saved_entries_for(unit)
                if saved_unit is not None:
                    aggregated["resources"].extend(saved_unit[0])
                    aggregated["capabilities"].extend(saved_unit[1])
                    logger.info("stage2.unit 跳过（已有保存数据） %s", label)
                    continue

            fingerprint = self._unit_fingerprint(unit)
            try:
                # The CLI must be called whenever this unit's configuration or the
                # analysis prompt changed, so generated code follows configuration.
                # Re-generating identical code every run only costs time.
                if self._build_is_current(build_state, label, fingerprint):
                    logger.info(
                        "stage2.unit step=build reused (unchanged) %s", label
                    )
                    engine_id = (
                        str(build_state[label].get("engine") or "") or engine_id
                    )
                else:
                    logger.info("stage2.unit step=build %s", label)
                    engine_id = (
                        self.build_analysis_code(
                            unit,
                            explicit_engine=explicit_engine,
                            progress_label=label,
                        )
                        or engine_id
                    )

                logger.info("stage2.unit step=run %s", label)
                raw = self.run_analysis(unit)

                logger.info("stage2.unit step=validate %s", label)
                self._validate_unit_output(raw, unit)
            except (PreflightAnalysisError, CliEngineError, OSError) as exc:
                message = f"{type(exc).__name__}: {exc}"
                logger.warning("stage2.unit failed %s -> %s", label, message)
                unit_failures.append((label, message))
                # Never drop a configured input silently; record it as failed.
                aggregated_key, entry = self._failed_unit_entry(label, unit, message)
                if entry is not None:
                    aggregated[aggregated_key].append(entry)
                continue

            for key in aggregated:
                aggregated[key].extend(raw.get(key) or [])

            # Only a fully validated unit may mark its generated code as current.
            build_state[label] = {"fingerprint": fingerprint, "engine": engine_id}
            self._save_build_state(build_state)
            logger.info("stage2.unit ok %s", label)

        if unit_failures and not aggregated["resources"] and not aggregated["capabilities"]:
            detail = "；".join(f"{label}: {message}" for label, message in unit_failures)
            raise PreflightAnalysisError(f"Stage 2 所有输入单元都失败：{detail}")

        raw = aggregated
        if not engine_id:
            engine_id = "reused_saved"
        self._write_receipt(
            units=units,
            resources=list(raw.get("resources") or []),
            capabilities=list(raw.get("capabilities") or []),
            failures=unit_failures,
            engine=engine_id,
        )

        resources = [
            _resource_record(item, index)
            for index, item in enumerate(raw.get("resources") or [], start=1)
        ]
        capabilities = [
            _capability_record(item, index)
            for index, item in enumerate(raw.get("capabilities") or [], start=1)
        ]
        if not resources and not capabilities:
            raise PreflightAnalysisError(
                "Stage 2 分析完成但 resources 与 capabilities 同时为空；禁止进入 Stage 3。"
            )

        self.generated_dir.mkdir(parents=True, exist_ok=True)
        try:
            resources_path, capabilities_path = write_preflight_files(
                resources=resources,
                capabilities=capabilities,
                resources_path=self.generated_dir / "resources.generated.yml",
                capabilities_path=self.generated_dir / "capabilities.generated.yml",
            )
        except ValueError as exc:
            raise PreflightAnalysisError(f"Stage 2 产物不符合 Task 输入契约：{exc}") from exc

        return Stage2MaterializationOutput(
            resources_path=resources_path,
            capabilities_path=capabilities_path,
            resource_analysis_path=self.receipt_path,
            function_analysis_path=self.receipt_path,
            cli_engine=engine_id,
        )


def _resource_record(item: Any, index: int) -> PreflightResourceRecord:
    if not isinstance(item, dict):
        raise PreflightAnalysisError(f"Stage 2 resources[{index}] 必须是映射。")
    resource_id = str(item.get("id") or item.get("resource_id") or "").strip()
    if not resource_id:
        raise PreflightAnalysisError(f"Stage 2 resources[{index}] 缺少 id。")
    resource_type = str(item.get("type") or item.get("resource_type") or "").strip()
    if not resource_type:
        raise PreflightAnalysisError(f"Stage 2 resource '{resource_id}' 缺少 type。")
    return PreflightResourceRecord(
        resource_id=resource_id,
        resource_type=resource_type,
        source_identity=str(item.get("source_identity") or resource_id).strip(),
        payload=item.get("payload"),
        summary=str(item.get("summary") or "").strip(),
        provider_id=str(item.get("provider_id") or "cli_project").strip(),
        availability=str(item.get("availability") or "").strip(),
        revision=item.get("revision"),
        metadata=dict(item.get("metadata") or {}),
    )


def _capability_record(item: Any, index: int) -> PreflightCapabilityRecord:
    if not isinstance(item, dict):
        raise PreflightAnalysisError(f"Stage 2 capabilities[{index}] 必须是映射。")
    capability_id = str(item.get("id") or item.get("capability_id") or "").strip()
    if not capability_id:
        raise PreflightAnalysisError(f"Stage 2 capabilities[{index}] 缺少 id。")
    return PreflightCapabilityRecord(
        capability_id=capability_id,
        # A function is a name; when the analysis did not characterise an action type,
        # the name is the action type.
        action_type=str(item.get("action_type") or capability_id).strip(),
        identity=str(item.get("identity") or "").strip(),
        provider_id=str(item.get("provider_id") or "cli_project").strip(),
        # A function is passed on as a name. Whatever description the analysis wrote
        # about "what it can do" is dropped here: it would read as the function's
        # ceiling to every later step.
        description=None,
        principal=item.get("principal"),
        security_domain=item.get("security_domain"),
        permissions=tuple(str(value) for value in (item.get("permissions") or [])),
        target_scope=dict(item.get("target_scope") or {}),
        availability=str(item.get("availability") or "").strip(),
        input_schema=dict(item.get("input_schema") or {}),
        can_observe_state=bool(item.get("can_observe_state", False)),
        observable_state=item.get("observable_state"),
        observation_operations=tuple(str(value) for value in (item.get("observation_operations") or [])),
        metadata=dict(item.get("metadata") or {}),
    )
