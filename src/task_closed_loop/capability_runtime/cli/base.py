from __future__ import annotations

import json
import shutil
import subprocess
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

from ..errors import CliEngineError


@dataclass(frozen=True)
class EngineStatus:
    engine_id: str
    state: str
    executable: Optional[str] = None
    version_output: Optional[str] = None
    detail: Optional[str] = None

    @property
    def ready(self) -> bool:
        return self.state == "ready"


@dataclass(frozen=True)
class CliRunResult:
    engine_id: str
    command: List[str]
    exit_code: int
    stdout: str
    stderr: str

    @property
    def succeeded(self) -> bool:
        return self.exit_code == 0


class CliEngineAdapter(ABC):
    engine_id: str
    executable_name: str
    status_cache_seconds: float = 30.0

    def __init__(self) -> None:
        self._status_cache: tuple[float, EngineStatus] | None = None

    def auth_probe_command(self, executable: str) -> List[str] | None:
        """Return a non-interactive authentication/health probe command.

        Real production adapters override this.  Returning ``None`` means the
        executable can only be classified as INSTALLED, never READY.
        """

        return None

    @staticmethod
    def _probe_failure_state(stdout: str, stderr: str) -> str:
        text = f"{stdout}\n{stderr}".lower()
        auth_markers = (
            "not logged in", "login", "sign in", "signin", "authentication",
            "unauthorized", "401", "credential", "api key", "oauth",
        )
        return "needs_auth" if any(marker in text for marker in auth_markers) else "unhealthy"

    def detect(self, *, force: bool = False) -> EngineStatus:
        now = time.monotonic()
        if not force and self._status_cache is not None:
            ts, cached = self._status_cache
            if now - ts <= self.status_cache_seconds:
                return cached

        executable = shutil.which(self.executable_name)
        if not executable:
            status = EngineStatus(self.engine_id, "missing")
            self._status_cache = (now, status)
            return status
        try:
            version = subprocess.run(
                [executable, "--version"],
                capture_output=True,
                text=True,
                timeout=10,
                encoding="utf-8",
                errors="replace",
            )
        except Exception as exc:
            status = EngineStatus(self.engine_id, "unhealthy", executable=executable, detail=str(exc))
            self._status_cache = (now, status)
            return status
        if version.returncode != 0:
            status = EngineStatus(
                self.engine_id,
                "unhealthy",
                executable=executable,
                detail=(version.stderr or version.stdout).strip(),
            )
            self._status_cache = (now, status)
            return status

        probe_command = self.auth_probe_command(executable)
        if not probe_command:
            status = EngineStatus(
                self.engine_id,
                "installed",
                executable=executable,
                version_output=(version.stdout or version.stderr).strip(),
                detail="installed, but adapter has no authentication probe",
            )
            self._status_cache = (now, status)
            return status
        try:
            probe = subprocess.run(
                probe_command,
                capture_output=True,
                text=True,
                timeout=30,
                encoding="utf-8",
                errors="replace",
            )
        except subprocess.TimeoutExpired:
            status = EngineStatus(
                self.engine_id,
                "unhealthy",
                executable=executable,
                version_output=(version.stdout or version.stderr).strip(),
                detail="authentication/health probe timed out",
            )
            self._status_cache = (now, status)
            return status
        except Exception as exc:
            status = EngineStatus(
                self.engine_id,
                "unhealthy",
                executable=executable,
                version_output=(version.stdout or version.stderr).strip(),
                detail=str(exc),
            )
            self._status_cache = (now, status)
            return status

        if probe.returncode == 0:
            state = "ready"
            detail = (probe.stdout or probe.stderr).strip()[-1000:] or None
        else:
            state = self._probe_failure_state(probe.stdout, probe.stderr)
            detail = (probe.stderr or probe.stdout).strip()[-2000:] or None
        status = EngineStatus(
            self.engine_id,
            state,
            executable=executable,
            version_output=(version.stdout or version.stderr).strip(),
            detail=detail,
        )
        self._status_cache = (now, status)
        return status

    @abstractmethod
    def build_command(self, *, mode: str, prompt: str, cwd: Path) -> List[str]:
        raise NotImplementedError

    def run(
        self,
        *,
        mode: str,
        prompt: str,
        cwd: Path,
        timeout_seconds: int | None = 900,
        on_output: Callable[[str, str], None] | None = None,
    ) -> CliRunResult:
        """Run the CLI, optionally reporting output while it is still working.

        `timeout_seconds=None` disables the limit. `on_output(stream, line)` is called
        for each line as it arrives, so a long run is observable instead of silent
        until exit.
        """

        status = self.detect()
        if not status.ready:
            raise CliEngineError(f"{self.engine_id} is not ready: {status.state}: {status.detail or ''}".rstrip())
        command = self.build_command(mode=mode, prompt=prompt, cwd=Path(cwd))

        if on_output is None:
            proc = subprocess.run(
                command,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                encoding="utf-8",
                errors="replace",
            )
            return CliRunResult(self.engine_id, command, proc.returncode, proc.stdout, proc.stderr)

        return self._run_streaming(
            command=command,
            cwd=Path(cwd),
            timeout_seconds=timeout_seconds,
            on_output=on_output,
        )

    def _run_streaming(
        self,
        *,
        command: List[str],
        cwd: Path,
        timeout_seconds: int | None,
        on_output: Callable[[str, str], None],
    ) -> CliRunResult:
        stdout_lines: List[str] = []
        stderr_lines: List[str] = []

        process = subprocess.Popen(
            command,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )

        def drain(stream, sink: List[str], name: str) -> None:
            try:
                for line in stream:
                    sink.append(line)
                    text = line.rstrip("\n")
                    if text:
                        try:
                            on_output(name, text)
                        except Exception:
                            # Reporting must never break the run it reports on.
                            pass
            finally:
                stream.close()

        threads = [
            threading.Thread(target=drain, args=(process.stdout, stdout_lines, "stdout"), daemon=True),
            threading.Thread(target=drain, args=(process.stderr, stderr_lines, "stderr"), daemon=True),
        ]
        for thread in threads:
            thread.start()

        try:
            returncode = process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            for thread in threads:
                thread.join(timeout=5)
            raise subprocess.TimeoutExpired(
                cmd=command,
                timeout=timeout_seconds,
                output="".join(stdout_lines),
                stderr="".join(stderr_lines),
            )

        for thread in threads:
            thread.join(timeout=10)

        return CliRunResult(
            self.engine_id,
            command,
            returncode,
            "".join(stdout_lines),
            "".join(stderr_lines),
        )

    @staticmethod
    def parse_json_stdout(result: CliRunResult):
        if not result.succeeded:
            raise CliEngineError(f"{result.engine_id} failed with exit code {result.exit_code}: {result.stderr[-2000:]}")
        try:
            return json.loads(result.stdout)
        except Exception as exc:
            raise CliEngineError(f"{result.engine_id} did not return valid JSON") from exc
