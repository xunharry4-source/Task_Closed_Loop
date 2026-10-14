"""Local Codex CLI adapter.

Stage 3/4/6/7 are specified as "call CLI/API", with the choice made by configuration.
Setting `TASK_LLM_ADAPTER` / `AUDIT_LLM_ADAPTER` to `codex_cli` routes Task
generation, audit, dimension generation and regeneration through the locally
installed `codex` binary.

Like `GemmaLLM`, this adapter only replaces the transport: every domain method and
all response parsing is inherited from `GeminiLLM`.

`codex exec` supports the contract natively:

    --output-schema <file>        enforce the final response shape
    --output-last-message <file>  write just the final message, no event parsing

so the schema does not have to be embedded in the prompt and no envelope has to be
guessed. Note that `codex exec` exits 0 even when the run fails, so success is
determined by the output file parsing as JSON, never by the exit code.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

from task_closed_loop.llm.cli_common import as_bool, whitelist_environment
from task_closed_loop.llm.gemini import (
    GeminiConfigurationError,
    GeminiLLM,
    GeminiResponseError,
    _jsonable,
)

CodexCliConfigurationError = GeminiConfigurationError
CodexCliResponseError = GeminiResponseError


class CodexCliRequestError(RuntimeError):
    pass


_SANDBOX_MODES = ("read-only", "workspace-write", "danger-full-access")

# Codex reads its credentials from ~/.codex (or CODEX_HOME); nothing else is needed.
# CLI authentication is independent of this project, so no project credential is
# ever forwarded.
_EXTRA_ENV = ("CODEX_HOME",)


def is_strict_schema(schema: Any) -> bool:
    """Whether `--output-schema` can be used for this schema.

    Codex validates the final response with strict structured outputs: every object
    must set `additionalProperties: false` and list all of its properties in
    `required`. Handing it an open-ended object (for example the free-form
    `current_facts` map) does not produce an error — the run hangs until it is killed
    — so such schemas must be enforced through the prompt instead.
    """

    if isinstance(schema, list):
        return all(is_strict_schema(item) for item in schema)
    if not isinstance(schema, dict):
        return True

    if schema.get("type") == "object" or "properties" in schema:
        if schema.get("additionalProperties") is not False:
            return False
        properties = schema.get("properties")
        if not isinstance(properties, dict):
            return False
        required = schema.get("required")
        if not isinstance(required, list) or set(required) != set(properties):
            return False

    for key, value in schema.items():
        if key == "required":
            continue
        if isinstance(value, (dict, list)) and not is_strict_schema(value):
            return False
    return True


def _failure_detail(*, stdout: str | None, stderr: str | None, budget: int = 800) -> str:
    """Summarize a failed run.

    `codex exec` echoes the whole prompt to stdout, so the tail is mostly prompt
    text while the real cause (for example `Error loading rules:`) appears at the
    start. Keep both ends and drop the middle.
    """

    parts = []
    for label, stream in (("stderr", stderr), ("stdout", stdout)):
        text = (stream or "").strip()
        if not text:
            continue
        if len(text) > budget * 2:
            text = f"{text[:budget]}\n…（省略 {len(text) - budget * 2} 字符）…\n{text[-budget:]}"
        parts.append(f"[{label}] {text}")
    return "\n".join(parts) or "(没有任何输出)"


class CodexCliLLM(GeminiLLM):
    """Drives `codex exec` headlessly with a native output schema."""

    def __init__(
        self,
        *,
        project_root,
        model: str = "",
        command: str = "codex",
        sandbox: str = "read-only",
        timeout_seconds: int = 600,
        max_retries: int = 2,
        ignore_rules: bool = True,
        ignore_user_config: bool = False,
        runner: Callable[..., subprocess.CompletedProcess] | None = None,
        **kwargs,
    ):
        sandbox = str(sandbox or "read-only").strip().lower()
        if sandbox not in _SANDBOX_MODES:
            raise CodexCliConfigurationError(
                "codex_cli sandbox 仅支持 read-only、workspace-write 或 danger-full-access。"
            )

        self.command = str(command or "codex").strip() or "codex"
        self.sandbox = sandbox
        self.timeout_seconds = int(timeout_seconds)
        self.max_retries = max(0, int(max_retries))
        self.ignore_rules = as_bool(ignore_rules, True)
        self.ignore_user_config = as_bool(ignore_user_config, False)
        self._runner = runner or subprocess.run
        # Model is optional: codex falls back to its configured default.
        self.cli_model = str(model or "").strip()

        super().__init__(
            project_root=project_root,
            model=self.cli_model or "codex-cli-default",
            # A non-None client bypasses the hosted-API key requirement in
            # GeminiLLM.__init__; this adapter never uses an API client.
            client=SimpleNamespace(),
            **kwargs,
        )

    def _resolve_executable(self) -> str:
        executable = shutil.which(self.command)
        if not executable:
            raise CodexCliConfigurationError(
                f"找不到 codex CLI 可执行文件：{self.command}。"
                "请确认已安装并在 PATH 中。"
            )
        return executable

    def _build_command(
        self,
        *,
        executable: str,
        workdir: Path,
        schema_path: Path | None,
        output_path: Path,
        prompt: str,
    ) -> list[str]:
        command = [
            executable,
            "exec",
            "--cd",
            str(workdir),
            "--skip-git-repo-check",
            "--sandbox",
            self.sandbox,
            # Do not leave session files behind for a pure reasoning call.
            "--ephemeral",
            "--output-last-message",
            str(output_path),
            "--color",
            "never",
        ]
        if schema_path is not None:
            command += ["--output-schema", str(schema_path)]
        if self.ignore_rules:
            # Task reasoning must not be affected by the user's local exec policy.
            command.append("--ignore-rules")
        if self.ignore_user_config:
            command.append("--ignore-user-config")
        if self.cli_model:
            command += ["--model", self.cli_model]
        command.append(prompt)
        return command

    def _render_prompt(
        self,
        *,
        role_key: str,
        input_payload: dict[str, Any],
        schema: dict[str, Any] | None,
        correction: str = "",
    ) -> str:
        prompt = self._role_prompt(role_key)
        # `schema` is supplied only when --output-schema cannot enforce it natively.
        schema_block = (
            "\n\n【输出 JSON Schema】\n"
            + json.dumps(schema, ensure_ascii=False, indent=2)
            + "\n只返回满足该 Schema 的 JSON 对象本身，不要输出解释或 Markdown 围栏。"
            if schema is not None
            else ""
        )
        return (
            prompt
            + "\n\n【本轮输入】\n"
            + json.dumps(_jsonable(input_payload), ensure_ascii=False, indent=2)
            + schema_block
            + "\n\n根据本轮输入完成上述职责，直接给出符合约定结构的最终 JSON 结果。"
            + correction
        )

    def _run_cli(
        self,
        *,
        prompt: str,
        schema: dict[str, Any] | None,
    ) -> str:
        executable = self._resolve_executable()
        env = whitelist_environment(extra_allow=_EXTRA_ENV)

        # An empty temporary workspace keeps the repository and cli_project/.env out
        # of the agent's working root and ancestor chain.
        with tempfile.TemporaryDirectory(prefix="codex-cli-reasoner-") as workdir_name:
            workdir = Path(workdir_name).resolve()
            output_path = workdir / "last_message.json"
            schema_path: Path | None = None
            if schema is not None:
                schema_path = workdir / "output_schema.json"
                schema_path.write_text(
                    json.dumps(schema, ensure_ascii=False),
                    encoding="utf-8",
                )

            command = self._build_command(
                executable=executable,
                workdir=workdir,
                schema_path=schema_path,
                output_path=output_path,
                prompt=prompt,
            )

            try:
                proc = self._runner(
                    command,
                    cwd=str(workdir),
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_seconds,
                    encoding="utf-8",
                    errors="replace",
                )
            except subprocess.TimeoutExpired as exc:
                raise CodexCliRequestError(
                    f"codex CLI 调用超时（{self.timeout_seconds}s）。"
                ) from exc
            except OSError as exc:
                raise CodexCliRequestError(
                    f"codex CLI 调用失败：{exc}"
                ) from exc

            # `codex exec` exits 0 even when the run failed (for example a broken
            # ~/.codex/rules file), so the written message is the only success signal.
            produced = (
                output_path.read_text(encoding="utf-8")
                if output_path.is_file()
                else ""
            )

        if not produced.strip():
            raise CodexCliRequestError(
                f"codex CLI 没有写出最终结果（退出码 {proc.returncode}）："
                + _failure_detail(stdout=proc.stdout, stderr=proc.stderr)
            )
        return produced

    def _create_interaction(
        self,
        *,
        role_key: str,
        input_payload: dict[str, Any],
        schema: dict[str, Any],
    ):
        correction = ""
        last_error: Exception | None = None
        # A non-strict schema would hang `codex exec`, so enforce it in the prompt.
        native_schema = schema if is_strict_schema(schema) else None
        prompt_schema = None if native_schema is not None else schema

        for attempt in range(self.max_retries + 1):
            prompt = self._render_prompt(
                role_key=role_key,
                input_payload=input_payload,
                schema=prompt_schema,
                correction=correction,
            )
            if self.prompt_cache is not None:
                self.prompt_cache.record(
                    provider="codex_cli",
                    model=self.cli_model or "(codex default)",
                    role_key=role_key,
                    prompt=prompt,
                    metadata={
                        "transport": "codex_exec",
                        "attempt": attempt + 1,
                        "native_output_schema": native_schema is not None,
                    },
                )

            self.debugger.request(
                adapter="codex_cli",
                model=self.cli_model or "(codex default)",
                role=role_key,
                prompt=prompt,
                response_contract=schema,
            )

            produced = self._run_cli(prompt=prompt, schema=native_schema)
            text = produced.strip()
            try:
                # Parse here so a malformed payload is retried rather than raised
                # straight through the inherited domain methods.
                json.loads(text)
            except json.JSONDecodeError as exc:
                last_error = exc
                correction = (
                    "\n\n上一次输出不是可解析的 JSON 对象，"
                    "请严格只输出符合约定结构的 JSON。"
                )
                continue

            return SimpleNamespace(output_text=text)

        raise CodexCliResponseError(
            f"codex CLI 连续 {self.max_retries + 1} 次未返回可解析 JSON：{last_error}"
        )
