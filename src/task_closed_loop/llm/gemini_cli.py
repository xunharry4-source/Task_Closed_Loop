"""Local Gemini CLI adapter.

Stage 3/4/6/7 are specified as "call CLI/API", with the choice made by configuration.
Setting `TASK_LLM_ADAPTER` / `AUDIT_LLM_ADAPTER` to `gemini_cli` routes Task
generation, audit, dimension generation and regeneration through the locally
installed `gemini` binary instead of the hosted API.

Like `GemmaLLM`, this adapter only replaces the transport: every domain method and
all response parsing is inherited from `GeminiLLM`.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

from task_closed_loop.llm.cli_common import whitelist_environment
from task_closed_loop.llm.gemini import (
    GeminiConfigurationError,
    GeminiLLM,
    GeminiResponseError,
    _jsonable,
)

GeminiCliConfigurationError = GeminiConfigurationError
GeminiCliResponseError = GeminiResponseError


class GeminiCliRequestError(RuntimeError):
    pass


_RESPONSE_KEYS = ("response", "output", "result", "text", "content")


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if len(lines) < 2:
        return stripped
    # Drop the opening fence (possibly ```json) and a matching closing fence.
    lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _first_json_object(text: str) -> str | None:
    """Return the outermost {...} span, so leading CLI warnings do not break parsing."""

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    return text[start : end + 1]


def extract_payload_text(stdout: str) -> str:
    """Pull the model's JSON payload out of whatever envelope the CLI returned.

    `gemini -o json` wraps the answer in a session envelope. The exact success shape
    is version-dependent, and the CLI may print warnings before it, so accept the
    known envelope keys and fall back to treating stdout itself as the payload.
    """

    text = (stdout or "").strip()
    if not text:
        raise GeminiCliResponseError("gemini CLI 没有任何输出。")

    try:
        envelope = json.loads(text)
    except json.JSONDecodeError:
        # The CLI may emit warnings (e.g. an approval-mode fallback notice) before
        # the JSON, so retry on the outermost object span.
        candidate = _first_json_object(text)
        if candidate is not None:
            try:
                envelope = json.loads(candidate)
            except json.JSONDecodeError:
                return _strip_code_fence(text)
        else:
            # Not an envelope at all: the payload may be bare or fenced JSON.
            return _strip_code_fence(text)

    if not isinstance(envelope, dict):
        return _strip_code_fence(text)

    error = envelope.get("error")
    if error:
        if isinstance(error, dict):
            message = str(
                error.get("message") or error.get("type") or error
            )
        else:
            message = str(error)
        raise GeminiCliRequestError(f"gemini CLI 返回错误：{message}")

    for key in _RESPONSE_KEYS:
        value = envelope.get(key)
        if isinstance(value, str) and value.strip():
            return _strip_code_fence(value)
        if isinstance(value, dict):
            # Already-structured payload; hand it back as JSON text.
            return json.dumps(value, ensure_ascii=False)

    # An envelope without a recognized response field may itself be the payload.
    return _strip_code_fence(text)


def build_cli_environment() -> dict[str, str]:
    """CLI authentication is independent of this project.

    No project credential is ever forwarded: the CLI uses its own signed-in account
    and its own quota, and nothing python-dotenv loaded from `.env` reaches it.
    """

    return whitelist_environment()


class GeminiCliLLM(GeminiLLM):
    """Drives the local `gemini` binary in headless, read-only mode."""

    def __init__(
        self,
        *,
        project_root,
        model: str = "",
        command: str = "gemini",
        approval_mode: str = "default",
        timeout_seconds: int = 300,
        max_retries: int = 2,
        runner: Callable[..., subprocess.CompletedProcess] | None = None,
        **kwargs,
    ):
        self.command = str(command or "gemini").strip() or "gemini"
        self.approval_mode = str(approval_mode or "default").strip() or "default"
        self.timeout_seconds = int(timeout_seconds)
        self.max_retries = max(0, int(max_retries))
        self._runner = runner or subprocess.run
        # Model is optional for the CLI: when unset the CLI picks its own default.
        self.cli_model = str(model or "").strip()

        super().__init__(
            project_root=project_root,
            model=self.cli_model or "gemini-cli-default",
            # A non-None client bypasses the hosted-API key requirement in
            # GeminiLLM.__init__; this adapter never uses an API client.
            client=SimpleNamespace(),
            **kwargs,
        )

    def _resolve_executable(self) -> str:
        executable = shutil.which(self.command)
        if not executable:
            raise GeminiCliConfigurationError(
                f"找不到 gemini CLI 可执行文件：{self.command}。"
                "请确认已安装并在 PATH 中。"
            )
        return executable

    def _build_command(self, executable: str, prompt: str) -> list[str]:
        command = [
            executable,
            "--prompt",
            prompt,
            "--output-format",
            "json",
            "--approval-mode",
            self.approval_mode,
        ]
        if self.cli_model:
            command += ["--model", self.cli_model]
        return command

    def _render_prompt(
        self,
        *,
        role_key: str,
        input_payload: dict[str, Any],
        schema: dict[str, Any],
        correction: str = "",
    ) -> str:
        prompt = self._role_prompt(role_key)
        return (
            prompt
            + "\n\n【本轮输入】\n"
            + json.dumps(_jsonable(input_payload), ensure_ascii=False, indent=2)
            + "\n\n【输出 JSON Schema】\n"
            + json.dumps(schema, ensure_ascii=False, indent=2)
            + "\n\n根据本轮输入完成上述职责。"
            + "只返回满足上面 JSON Schema 的 JSON 对象本身，"
            + "不要输出解释、Markdown 围栏或任何额外文本。"
            + correction
        )

    def _run_cli(self, prompt: str) -> str:
        executable = self._resolve_executable()
        command = self._build_command(executable, prompt)
        env = build_cli_environment()

        # Run in an empty temporary directory so the repository and the CLI Project
        # .env are never in the process's ancestor chain.
        with tempfile.TemporaryDirectory(prefix="gemini-cli-reasoner-") as workdir:
            try:
                proc = self._runner(
                    command,
                    cwd=str(Path(workdir).resolve()),
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_seconds,
                    encoding="utf-8",
                    errors="replace",
                )
            except subprocess.TimeoutExpired as exc:
                raise GeminiCliRequestError(
                    f"gemini CLI 调用超时（{self.timeout_seconds}s）。"
                ) from exc
            except OSError as exc:
                raise GeminiCliRequestError(
                    f"gemini CLI 调用失败：{exc}"
                ) from exc

        if proc.returncode != 0:
            # A failing run still prints a structured error envelope — on stderr for
            # auth/quota failures. Surface that message instead of the whole blob.
            for stream in (proc.stdout, proc.stderr):
                try:
                    extract_payload_text(stream or "")
                except GeminiCliRequestError as exc:
                    raise GeminiCliRequestError(
                        f"{exc}"
                        + (
                            "\n提示：CLI 认证独立于本项目，"
                            "请先在终端运行 `gemini` 完成登录。"
                            if "Auth method" in str(exc)
                            else ""
                        )
                    ) from None
                except GeminiCliResponseError:
                    continue
            raise GeminiCliRequestError(
                f"gemini CLI 退出码 {proc.returncode}："
                f"{(proc.stderr or proc.stdout or '')[-2000:]}"
            )
        return proc.stdout or ""

    def _create_interaction(
        self,
        *,
        role_key: str,
        input_payload: dict[str, Any],
        schema: dict[str, Any],
    ):
        correction = ""
        last_error: Exception | None = None

        for attempt in range(self.max_retries + 1):
            prompt = self._render_prompt(
                role_key=role_key,
                input_payload=input_payload,
                schema=schema,
                correction=correction,
            )
            self.debugger.request(
                adapter="gemini_cli",
                model=self.cli_model or "(cli default)",
                role=role_key,
                prompt=prompt,
                response_contract=schema,
            )

            stdout = self._run_cli(prompt)
            try:
                payload_text = extract_payload_text(stdout)
                # Parse here so a malformed payload is retried rather than raised
                # straight through the inherited domain methods.
                json.loads(payload_text)
            except GeminiCliRequestError:
                # A CLI-side error (auth, quota, model) will not be fixed by asking
                # the model again.
                raise
            except (GeminiCliResponseError, json.JSONDecodeError) as exc:
                last_error = exc
                correction = (
                    "\n\n上一次输出不是可解析的 JSON 对象，"
                    "请严格只输出符合 Schema 的 JSON。"
                )
                continue

            return SimpleNamespace(output_text=payload_text)

        raise GeminiCliResponseError(
            f"gemini CLI 连续 {self.max_retries + 1} 次未返回可解析 JSON：{last_error}"
        )
