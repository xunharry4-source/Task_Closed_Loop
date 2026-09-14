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
from task_closed_loop.capability_runtime.secrets import DotEnvSecretResolver

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
    input_id: str
    directory: str
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {
            "id": self.input_id,
            "kind": "local_directory",
            "directory": self.directory,
            "description": self.description,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class RemoteResourceInput:
    input_id: str
    kind: str
    function_id: str
    scope: dict[str, Any] = field(default_factory=dict)
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {
            "id": self.input_id,
            "kind": self.kind,
            "function_id": self.function_id,
            "scope": dict(self.scope),
            "description": self.description,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class FunctionInput:
    function_id: str
    kind: str
    description: str = ""
    secret_refs: tuple[str, ...] = ()
    operations: tuple[str, ...] = ()
    scope: dict[str, Any] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {
            "id": self.function_id,
            "kind": self.kind,
            "description": self.description,
            "secret_refs": list(self.secret_refs),
            "operations": list(self.operations),
            "scope": dict(self.scope),
            "config": dict(self.config),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class PreflightInputBundle:
    local_resources: tuple[LocalResourceInput, ...] = ()
    remote_resources: tuple[RemoteResourceInput, ...] = ()
    functions: tuple[FunctionInput, ...] = ()

    @property
    def total_count(self) -> int:
        return len(self.local_resources) + len(self.remote_resources) + len(self.functions)

    @property
    def secret_refs(self) -> tuple[str, ...]:
        return tuple(sorted({ref for item in self.functions for ref in item.secret_refs}))

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


def _unique_id(raw: dict, *, section: str, index: int, key: str = "id") -> str:
    value = str(raw.get(key) or "").strip()
    if not value:
        raise PreflightSourceConfigurationError(f"{section}[{index}] 缺少 {key}。")
    return value


def load_preflight_inputs(config: dict, *, project_root: str | Path) -> PreflightInputBundle:
    """Load the only Stage 2 input shape allowed by the architecture lock."""

    if "preflight_sources" in (config or {}):
        raise PreflightSourceConfigurationError(
            "已废弃 preflight_sources.sources 单列表。V1.1 固定使用 preflight_inputs.local_resources / remote_resources / functions。"
        )

    section = (config or {}).get("preflight_inputs") or {}
    if not section.get("enabled", True):
        return PreflightInputBundle()

    root = Path(project_root).resolve()
    local_raw = section.get("local_resources") or []
    remote_raw = section.get("remote_resources") or []
    function_raw = section.get("functions") or []
    for name, values in (
        ("local_resources", local_raw),
        ("remote_resources", remote_raw),
        ("functions", function_raw),
    ):
        if not isinstance(values, list):
            raise PreflightSourceConfigurationError(f"preflight_inputs.{name} 必须是列表。")

    local: list[LocalResourceInput] = []
    remote: list[RemoteResourceInput] = []
    functions: list[FunctionInput] = []
    seen: set[str] = set()

    for index, item in enumerate(local_raw, start=1):
        if not isinstance(item, dict):
            raise PreflightSourceConfigurationError(f"local_resources[{index}] 必须是映射。")
        _assert_no_inline_secret(item, where=f"local_resources[{index}]")
        input_id = _unique_id(item, section="local_resources", index=index)
        if input_id in seen:
            raise PreflightSourceConfigurationError(f"Stage 2 输入 id 重复：{input_id}")
        seen.add(input_id)
        directory = str(item.get("directory") or "").strip()
        if not directory:
            raise PreflightSourceConfigurationError(f"local resource '{input_id}' 缺少 directory。")
        path = Path(directory)
        resolved = path if path.is_absolute() else (root / path)
        resolved = resolved.resolve()
        if not resolved.is_dir():
            raise PreflightSourceConfigurationError(
                f"local resource '{input_id}' 配置目录不存在或不是目录：{resolved}"
            )
        local.append(
            LocalResourceInput(
                input_id=input_id,
                directory=str(resolved),
                description=str(item.get("description") or "").strip(),
                metadata=dict(item.get("metadata") or {}),
            )
        )

    function_ids: set[str] = set()
    for index, item in enumerate(function_raw, start=1):
        if not isinstance(item, dict):
            raise PreflightSourceConfigurationError(f"functions[{index}] 必须是映射。")
        _assert_no_inline_secret(item, where=f"functions[{index}]")
        function_id = _unique_id(item, section="functions", index=index)
        if function_id in seen:
            raise PreflightSourceConfigurationError(f"Stage 2 输入 id 重复：{function_id}")
        seen.add(function_id)
        function_ids.add(function_id)
        kind = str(item.get("kind") or "").strip()
        if not kind:
            raise PreflightSourceConfigurationError(f"function '{function_id}' 缺少 kind。")
        functions.append(
            FunctionInput(
                function_id=function_id,
                kind=kind,
                description=str(item.get("description") or "").strip(),
                secret_refs=tuple(str(v).strip() for v in (item.get("secret_refs") or []) if str(v).strip()),
                operations=tuple(str(v).strip() for v in (item.get("operations") or []) if str(v).strip()),
                scope=dict(item.get("scope") or {}),
                config=dict(item.get("config") or {}),
                metadata=dict(item.get("metadata") or {}),
            )
        )

    for index, item in enumerate(remote_raw, start=1):
        if not isinstance(item, dict):
            raise PreflightSourceConfigurationError(f"remote_resources[{index}] 必须是映射。")
        _assert_no_inline_secret(item, where=f"remote_resources[{index}]")
        input_id = _unique_id(item, section="remote_resources", index=index)
        if input_id in seen:
            raise PreflightSourceConfigurationError(f"Stage 2 输入 id 重复：{input_id}")
        seen.add(input_id)
        kind = str(item.get("kind") or "").strip()
        function_id = str(item.get("function_id") or "").strip()
        if not kind or not function_id:
            raise PreflightSourceConfigurationError(
                f"remote resource '{input_id}' 必须同时声明 kind 与 function_id。"
            )
        if function_id not in function_ids:
            raise PreflightSourceConfigurationError(
                f"remote resource '{input_id}' 引用未配置 function_id：{function_id}"
            )
        remote.append(
            RemoteResourceInput(
                input_id=input_id,
                kind=kind,
                function_id=function_id,
                scope=dict(item.get("scope") or {}),
                description=str(item.get("description") or "").strip(),
                metadata=dict(item.get("metadata") or {}),
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
        cli_timeout_seconds: int = 900,
        analysis_timeout_seconds: int = 600,
    ):
        self.project_root = Path(project_root).resolve()
        self.prompt_text = prompt_text
        self.router = CliEngineRouter(
            adapters if adapters is not None else default_cli_adapters(),
            preferred=list(preferred_engines) if preferred_engines else None,
        )
        self.secret_resolver = secret_resolver or DotEnvSecretResolver(self.project_root / ".env")
        self.cli_timeout_seconds = int(cli_timeout_seconds)
        self.analysis_timeout_seconds = int(analysis_timeout_seconds)

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
    def resource_analysis_path(self) -> Path:
        return self.analysis_dir / "results" / "resources.analysis.yml"

    @property
    def function_analysis_path(self) -> Path:
        return self.analysis_dir / "results" / "functions.analysis.yml"

    def has_analysis_code(self) -> bool:
        return self.entrypoint.is_file()

    def build_analysis_code(
        self,
        inputs: PreflightInputBundle | Sequence[PreflightSource],
        *,
        explicit_engine: str | None = None,
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
                    timeout_seconds=self.cli_timeout_seconds,
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
        try:
            proc = subprocess.run(
                command,
                input=payload,
                cwd=str(self.analysis_dir),
                env=env,
                capture_output=True,
                text=True,
                timeout=self.analysis_timeout_seconds,
                encoding="utf-8",
                errors="replace",
            )
        except subprocess.TimeoutExpired as exc:
            raise PreflightAnalysisError(
                f"Stage 2 分析代码执行超时（{self.analysis_timeout_seconds}s）。"
            ) from exc

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

    def _validated_generated_evidence(
        self, evidence: Any, *, source_type: str, source_id: str, allowed_operations: set[str] | None = None
    ) -> list[dict[str, Any]]:
        if not isinstance(evidence, list) or not evidence:
            raise PreflightAnalysisError(
                f"Stage 2 {source_type} '{source_id}' 缺少结构化 evidence；CLI 的文字结论不能直接成为现实事实。"
            )
        valid_status = {"success", "verified_empty", "unavailable", "failed"}
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        artifact_root = (self.project_root / "artifacts" / "preflight").resolve()
        for index, raw in enumerate(evidence, start=1):
            if not isinstance(raw, dict):
                raise PreflightAnalysisError(
                    f"Stage 2 {source_type} '{source_id}' evidence[{index}] 必须是映射，不接受字符串自报证据。"
                )
            evidence_id = str(raw.get("evidence_id") or "").strip()
            status = str(raw.get("status") or "").strip().lower()
            operation = str(raw.get("operation") or "").strip()
            observed_via = str(raw.get("observed_via") or "").strip()
            if not evidence_id or evidence_id in seen:
                raise PreflightAnalysisError(
                    f"Stage 2 {source_type} '{source_id}' evidence 必须有唯一 evidence_id。"
                )
            seen.add(evidence_id)
            if status not in valid_status:
                raise PreflightAnalysisError(
                    f"Stage 2 evidence '{evidence_id}' status 必须是 {sorted(valid_status)}。"
                )
            if not operation or not observed_via:
                raise PreflightAnalysisError(
                    f"Stage 2 evidence '{evidence_id}' 缺少 operation/observed_via。"
                )
            if allowed_operations and operation not in allowed_operations:
                raise PreflightAnalysisError(
                    f"Stage 2 evidence '{evidence_id}' operation={operation} 不在配置允许操作 {sorted(allowed_operations)} 中。"
                )
            if str(raw.get("source_id") or "").strip() != source_id:
                raise PreflightAnalysisError(
                    f"Stage 2 evidence '{evidence_id}' source_id 必须等于 {source_id}。"
                )
            if str(raw.get("source_type") or "").strip() != source_type:
                raise PreflightAnalysisError(
                    f"Stage 2 evidence '{evidence_id}' source_type 必须等于 {source_type}。"
                )
            has_inline = "raw_observation" in raw
            artifact_ref = str(raw.get("artifact_ref") or "").strip()
            if not has_inline and not artifact_ref:
                raise PreflightAnalysisError(
                    f"Stage 2 evidence '{evidence_id}' 必须包含 raw_observation 或 artifact_ref，不能只有结论。"
                )
            normalized = dict(raw)
            if artifact_ref:
                candidate = Path(artifact_ref)
                resolved = candidate.resolve() if candidate.is_absolute() else (self.project_root / candidate).resolve()
                try:
                    resolved.relative_to(artifact_root)
                except ValueError as exc:
                    raise PreflightAnalysisError(
                        f"Stage 2 evidence '{evidence_id}' artifact_ref 必须位于 cli_project/artifacts/preflight/。"
                    ) from exc
                if not resolved.is_file():
                    raise PreflightAnalysisError(
                        f"Stage 2 evidence '{evidence_id}' artifact_ref 不存在：{resolved}"
                    )
                normalized["artifact_ref"] = resolved.relative_to(self.project_root).as_posix()
                normalized["artifact_sha256"] = hashlib.sha256(resolved.read_bytes()).hexdigest()
            if has_inline:
                serialized = json.dumps(raw.get("raw_observation"), ensure_ascii=False, sort_keys=True, default=str)
                normalized["observation_sha256"] = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
            out.append(normalized)
        return out

    def _validate_implementation_files(self, values: Any, *, source_label: str) -> list[str]:
        if not isinstance(values, list) or not values:
            raise PreflightAnalysisError(
                f"Stage 2 {source_label} 缺少 implementation_files；必须证明实际调用/分析代码已落在 cli_project。"
            )
        normalized: list[str] = []
        for raw in values:
            rel = str(raw or "").strip()
            if not rel:
                raise PreflightAnalysisError(f"Stage 2 {source_label} implementation_files 含空路径。")
            candidate = (self.project_root / rel).resolve()
            try:
                candidate.relative_to(self.project_root)
            except ValueError as exc:
                raise PreflightAnalysisError(
                    f"Stage 2 {source_label} implementation file 越出 cli_project：{rel}"
                ) from exc
            if not candidate.is_file():
                raise PreflightAnalysisError(
                    f"Stage 2 {source_label} 声明的 implementation file 不存在：{rel}"
                )
            normalized.append(candidate.relative_to(self.project_root).as_posix())
        return normalized

    def _validate_analysis_coverage(self, raw: dict[str, Any], inputs: PreflightInputBundle) -> dict[str, dict[str, Any]]:
        resource_analysis = raw.get("resource_analysis")
        function_analysis = raw.get("function_analysis")
        if not isinstance(resource_analysis, list):
            raise PreflightAnalysisError("Stage 2 结果缺少 resource_analysis 列表。")
        if not isinstance(function_analysis, list):
            raise PreflightAnalysisError("Stage 2 结果缺少 function_analysis 列表。")

        local_by_id = {item.input_id: item for item in inputs.local_resources}
        remote_by_id = {item.input_id: item for item in inputs.remote_resources}
        expected_resources = set(local_by_id) | set(remote_by_id)
        observed_resource_ids = [
            str(item.get("input_id") or "").strip()
            for item in resource_analysis if isinstance(item, dict)
        ]
        duplicates = sorted({value for value in observed_resource_ids if value and observed_resource_ids.count(value) > 1})
        if duplicates:
            raise PreflightAnalysisError(
                "Stage 2 resource_analysis input_id 必须唯一；重复：" + ", ".join(duplicates)
            )
        observed_resources = set(observed_resource_ids)
        missing_resources = sorted(expected_resources - observed_resources)
        if missing_resources:
            raise PreflightAnalysisError(
                "Stage 2 没有为以下资源输入生成分析文件记录：" + ", ".join(missing_resources)
            )

        evidence_index: dict[str, dict[str, Any]] = {}
        for item in resource_analysis:
            if not isinstance(item, dict):
                raise PreflightAnalysisError("resource_analysis 元素必须是映射。")
            input_id = str(item.get("input_id") or "").strip()
            for field_name in ("input_id", "directory_structure", "data_summary", "content_summary", "availability_status"):
                if field_name not in item:
                    raise PreflightAnalysisError(
                        f"resource_analysis[{input_id or '?'}] 缺少 {field_name}。"
                    )
            status = str(item.get("availability_status") or "").strip().lower()
            if status not in {"available", "unavailable", "failed"}:
                raise PreflightAnalysisError(
                    f"resource_analysis[{input_id}] availability_status 必须显式为 available/unavailable/failed。"
                )
            self._validate_implementation_files(
                item.get("implementation_files"), source_label=f"resource_analysis[{input_id}]"
            )
            if input_id in local_by_id:
                host_evidence = self._local_tree_receipt(local_by_id[input_id])
                existing = item.get("evidence")
                if existing is None:
                    existing = []
                if not isinstance(existing, list):
                    raise PreflightAnalysisError(f"resource_analysis[{input_id}].evidence 必须是列表。")
                # Local truth is independently verified by Host, not trusted from CLI text.
                normalized_evidence = [host_evidence]
                item["evidence"] = normalized_evidence
                if status != "available":
                    raise PreflightAnalysisError(
                        f"本地目录 '{input_id}' 已由 Host 验证存在并扫描成功，CLI 不得标记为 {status}。"
                    )
            elif input_id in remote_by_id:
                allowed = None
                function = next((f for f in inputs.functions if f.function_id == remote_by_id[input_id].function_id), None)
                if function is not None and function.operations:
                    allowed = set(function.operations)
                normalized_evidence = self._validated_generated_evidence(
                    item.get("evidence"), source_type="remote_resource", source_id=input_id, allowed_operations=allowed
                )
                item["evidence"] = normalized_evidence
            else:
                raise PreflightAnalysisError(f"Stage 2 返回未配置的 resource_analysis input_id：{input_id}")
            for ev in item["evidence"]:
                if ev["evidence_id"] in evidence_index:
                    raise PreflightAnalysisError(f"Stage 2 evidence_id 重复：{ev['evidence_id']}")
                evidence_index[ev["evidence_id"]] = ev

        function_by_id = {item.function_id: item for item in inputs.functions}
        expected_functions = set(function_by_id)
        observed_function_ids = [
            str(item.get("function_id") or "").strip()
            for item in function_analysis if isinstance(item, dict)
        ]
        duplicates = sorted({value for value in observed_function_ids if value and observed_function_ids.count(value) > 1})
        if duplicates:
            raise PreflightAnalysisError(
                "Stage 2 function_analysis function_id 必须唯一；重复：" + ", ".join(duplicates)
            )
        observed_functions = set(observed_function_ids)
        missing_functions = sorted(expected_functions - observed_functions)
        if missing_functions:
            raise PreflightAnalysisError(
                "Stage 2 没有为以下功能配置生成分析文件记录：" + ", ".join(missing_functions)
            )
        for item in function_analysis:
            if not isinstance(item, dict):
                raise PreflightAnalysisError("function_analysis 元素必须是映射。")
            function_id = str(item.get("function_id") or "").strip()
            if function_id not in function_by_id:
                raise PreflightAnalysisError(f"Stage 2 返回未配置的 function_id：{function_id}")
            for field_name in ("function_id", "available_operations", "observed_data_summary", "availability_status"):
                if field_name not in item:
                    raise PreflightAnalysisError(
                        f"function_analysis[{function_id or '?'}] 缺少 {field_name}。"
                    )
            status = str(item.get("availability_status") or "").strip().lower()
            if status not in {"available", "unavailable", "failed"}:
                raise PreflightAnalysisError(
                    f"function_analysis[{function_id}] availability_status 必须显式为 available/unavailable/failed。"
                )
            self._validate_implementation_files(
                item.get("implementation_files"), source_label=f"function_analysis[{function_id}]"
            )
            configured_ops = set(function_by_id[function_id].operations)
            reported_ops = {str(value).strip() for value in (item.get("available_operations") or []) if str(value).strip()}
            if configured_ops and not reported_ops.issubset(configured_ops):
                raise PreflightAnalysisError(
                    f"function_analysis[{function_id}] 报告了配置之外的操作：{sorted(reported_ops - configured_ops)}"
                )
            if status == "available" and not reported_ops:
                raise PreflightAnalysisError(
                    f"function_analysis[{function_id}] 标记 available 但没有任何实测 available_operations。"
                )
            normalized_evidence = self._validated_generated_evidence(
                item.get("evidence"), source_type="function", source_id=function_id,
                allowed_operations=(configured_ops or None),
            )
            item["evidence"] = normalized_evidence
            if status == "available" and not any(ev["status"] in {"success", "verified_empty"} for ev in normalized_evidence):
                raise PreflightAnalysisError(
                    f"function_analysis[{function_id}] 标记 available，但没有 success/verified_empty 执行证据。"
                )
            for ev in normalized_evidence:
                if ev["evidence_id"] in evidence_index:
                    raise PreflightAnalysisError(f"Stage 2 evidence_id 重复：{ev['evidence_id']}")
                evidence_index[ev["evidence_id"]] = ev
        return evidence_index

    def _bind_output_provenance(
        self, raw: dict[str, Any], inputs: PreflightInputBundle, evidence_index: dict[str, dict[str, Any]]
    ) -> None:
        configured_resource_ids = {item.input_id for item in inputs.local_resources + inputs.remote_resources}
        configured_function_ids = {item.function_id for item in inputs.functions}
        resource_status = {
            str(item.get("input_id") or "").strip(): str(item.get("availability_status") or "").strip().lower()
            for item in (raw.get("resource_analysis") or []) if isinstance(item, dict)
        }
        function_status = {
            str(item.get("function_id") or "").strip(): str(item.get("availability_status") or "").strip().lower()
            for item in (raw.get("function_analysis") or []) if isinstance(item, dict)
        }
        evidence_by_source: dict[str, list[str]] = {}
        for evidence_id, evidence in evidence_index.items():
            evidence_by_source.setdefault(str(evidence.get("source_id") or ""), []).append(evidence_id)

        for index, item in enumerate(raw.get("resources") or [], start=1):
            if not isinstance(item, dict):
                raise PreflightAnalysisError(f"Stage 2 resources[{index}] 必须是映射。")
            if "availability" not in item:
                raise PreflightAnalysisError(f"Stage 2 resources[{index}] 必须显式声明 availability。")
            metadata = dict(item.get("metadata") or {})
            source_ids = metadata.get("source_input_ids") or []
            if not isinstance(source_ids, list) or not source_ids:
                raise PreflightAnalysisError(
                    f"Stage 2 resource '{item.get('id', index)}' metadata.source_input_ids 必须关联实际配置资源。"
                )
            normalized_sources = [str(value).strip() for value in source_ids if str(value).strip()]
            unknown = sorted(set(normalized_sources) - configured_resource_ids)
            if unknown:
                raise PreflightAnalysisError(
                    f"Stage 2 resource '{item.get('id', index)}' 引用了未知 source_input_ids：{unknown}"
                )
            evidence_ids = sorted({eid for sid in normalized_sources for eid in evidence_by_source.get(sid, [])})
            if not evidence_ids:
                raise PreflightAnalysisError(
                    f"Stage 2 resource '{item.get('id', index)}' 没有可追溯 Stage 2 evidence。"
                )
            declared_availability = str(item.get("availability") or "").strip().lower()
            if declared_availability not in {"available", "unavailable", "failed"}:
                raise PreflightAnalysisError(
                    f"Stage 2 resource '{item.get('id', index)}' availability 必须是 available/unavailable/failed。"
                )
            source_states = {resource_status.get(source_id, "") for source_id in normalized_sources}
            expected_availability = (
                "available" if "available" in source_states
                else "failed" if "failed" in source_states
                else "unavailable"
            )
            if declared_availability != expected_availability:
                raise PreflightAnalysisError(
                    f"Stage 2 resource '{item.get('id', index)}' availability={declared_availability} "
                    f"与来源分析状态 {sorted(source_states)} 不一致；应为 {expected_availability}。"
                )
            metadata["source_input_ids"] = normalized_sources
            metadata["stage2_evidence_ids"] = evidence_ids
            item["metadata"] = metadata

        for index, item in enumerate(raw.get("capabilities") or [], start=1):
            if not isinstance(item, dict):
                raise PreflightAnalysisError(f"Stage 2 capabilities[{index}] 必须是映射。")
            if "availability" not in item:
                raise PreflightAnalysisError(f"Stage 2 capabilities[{index}] 必须显式声明 availability。")
            metadata = dict(item.get("metadata") or {})
            function_id = str(metadata.get("source_function_id") or "").strip()
            if not function_id or function_id not in configured_function_ids:
                raise PreflightAnalysisError(
                    f"Stage 2 capability '{item.get('id', index)}' metadata.source_function_id 必须关联已配置 function。"
                )
            evidence_ids = sorted(evidence_by_source.get(function_id, []))
            if not evidence_ids:
                raise PreflightAnalysisError(
                    f"Stage 2 capability '{item.get('id', index)}' 没有可追溯 Stage 2 evidence。"
                )
            declared_availability = str(item.get("availability") or "").strip().lower()
            if declared_availability not in {"available", "unavailable", "failed"}:
                raise PreflightAnalysisError(
                    f"Stage 2 capability '{item.get('id', index)}' availability 必须是 available/unavailable/failed。"
                )
            expected_availability = function_status.get(function_id, "")
            if declared_availability != expected_availability:
                raise PreflightAnalysisError(
                    f"Stage 2 capability '{item.get('id', index)}' availability={declared_availability} "
                    f"与 function '{function_id}' 分析状态 {expected_availability} 不一致。"
                )
            metadata["source_function_id"] = function_id
            metadata["stage2_evidence_ids"] = evidence_ids
            item["metadata"] = metadata

    @staticmethod
    def _write_analysis_file(path: Path, producer: str, items: list[Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            yaml.safe_dump(
                {"schema_version": "1.1", "producer": producer, "items": items},
                allow_unicode=True,
                sort_keys=False,
            ),
            encoding="utf-8",
        )

    def materialize(
        self,
        inputs: PreflightInputBundle,
        *,
        explicit_engine: str | None = None,
    ) -> Stage2MaterializationOutput:
        if inputs.total_count == 0:
            raise PreflightSourceConfigurationError(
                "Stage 2 没有任何配置输入；必须至少配置 local_resources / remote_resources / functions 之一。"
            )

        # The locked architecture requires Stage 2 to call the CLI every production
        # run so analysis/connector code can evolve with current configuration.
        engine_id = self.build_analysis_code(inputs, explicit_engine=explicit_engine)
        raw = self.run_analysis(inputs)
        evidence_index = self._validate_analysis_coverage(raw, inputs)
        self._bind_output_provenance(raw, inputs, evidence_index)

        resource_analysis = list(raw.get("resource_analysis") or [])
        function_analysis = list(raw.get("function_analysis") or [])
        self._write_analysis_file(
            self.resource_analysis_path, "preflight.resource_analysis", resource_analysis
        )
        self._write_analysis_file(
            self.function_analysis_path, "preflight.function_analysis", function_analysis
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
            resource_analysis_path=self.resource_analysis_path,
            function_analysis_path=self.function_analysis_path,
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
    action_type = str(item.get("action_type") or "").strip()
    if not action_type:
        raise PreflightAnalysisError(f"Stage 2 capability '{capability_id}' 缺少 action_type。")
    return PreflightCapabilityRecord(
        capability_id=capability_id,
        action_type=action_type,
        provider_id=str(item.get("provider_id") or "cli_project").strip(),
        description=item.get("description"),
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
