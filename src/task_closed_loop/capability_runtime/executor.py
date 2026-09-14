from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Tuple

from .contracts import CapabilityManifest, CapabilityRequest, CapabilityResult
from .errors import CapabilityExecutionError
from .io_utils import read_yaml
from .registry import CapabilityRegistry
from .secrets import DotEnvSecretResolver
from .verification import ExecutionVerificationEngine


class CapabilityExecutor:
    def __init__(
        self,
        project_root: Path,
        registry: CapabilityRegistry,
        secret_resolver=None,
        timeout_seconds: int = 300,
        verification_engine: ExecutionVerificationEngine | None = None,
    ):
        self.project_root = Path(project_root).resolve()
        self.registry = registry
        self.secret_resolver = secret_resolver or DotEnvSecretResolver(self.project_root / ".env")
        self.timeout_seconds = timeout_seconds
        self.verification_engine = verification_engine or ExecutionVerificationEngine()

    def _load_manifest(self, capability_id: str) -> tuple[CapabilityManifest, Path]:
        entry = self.registry.find(capability_id)
        if not entry:
            raise CapabilityExecutionError(f"verified capability not found: {capability_id}")
        if entry.get("status") not in {"verified", "enabled"}:
            raise CapabilityExecutionError(f"capability is not executable: {capability_id}")
        capability_dir = (self.project_root / entry["implementation_path"]).resolve()
        if self.project_root not in capability_dir.parents:
            raise CapabilityExecutionError("registry implementation path escapes project root")
        manifest = CapabilityManifest.from_dict(read_yaml(capability_dir / "manifest.yml"))
        return manifest, capability_dir

    def _run_process(self, request: CapabilityRequest) -> Tuple[CapabilityManifest, Dict[str, Any], list[dict], list[str], Dict[str, Any], Path]:
        manifest, capability_dir = self._load_manifest(request.capability_id)
        missing = [field for field in manifest.input_fields if field not in request.inputs]
        if missing:
            raise CapabilityExecutionError(f"missing capability inputs: {missing}")
        entrypoint = (capability_dir / "implementation" / manifest.entrypoint_file).resolve()
        implementation_root = (capability_dir / "implementation").resolve()
        if implementation_root not in entrypoint.parents and entrypoint != implementation_root:
            raise CapabilityExecutionError("entrypoint escapes capability implementation directory")
        if not entrypoint.exists():
            raise CapabilityExecutionError(f"entrypoint missing: {entrypoint}")

        secrets = self.secret_resolver.resolve(manifest.secret_refs)
        artifact_dir = self.project_root / "artifacts" / request.request_id
        temp_dir = self.project_root / "temp" / request.request_id
        artifact_dir.mkdir(parents=True, exist_ok=True)
        temp_dir.mkdir(parents=True, exist_ok=True)
        context: Dict[str, Any] = {
            "request_id": request.request_id,
            "task_id": request.task_id,
            "secrets": secrets,
            "artifact_dir": str(artifact_dir),
            "temp_dir": str(temp_dir),
            "permissions": dict(manifest.permissions),
        }
        runner = Path(__file__).with_name("capability_runner.py").resolve()
        command = [sys.executable, "-I", str(runner), "--entrypoint", str(entrypoint), "--function", manifest.entrypoint_function]
        # Only non-secret runtime variables are exposed. Real credential values
        # are never copied into the child process environment.
        env = {
            "PATH": os.environ.get("PATH", ""),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONIOENCODING": "utf-8",
            "EXECUTION_PROJECT_CAPABILITY_MODE": "1",
        }
        payload = json.dumps({"inputs": dict(request.inputs), "context": context}, ensure_ascii=False)
        try:
            proc = subprocess.run(
                command,
                input=payload,
                cwd=str(capability_dir),
                env=env,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                encoding="utf-8",
                errors="replace",
            )
        except subprocess.TimeoutExpired as exc:
            raise CapabilityExecutionError(f"capability process timed out after {self.timeout_seconds}s") from exc
        try:
            message = json.loads(proc.stdout.strip() or "{}")
        except Exception as exc:
            raise CapabilityExecutionError(
                f"capability runner returned invalid JSON (exit={proc.returncode}): stdout={proc.stdout[-1000:]!r}, stderr={proc.stderr[-1000:]!r}"
            ) from exc
        if proc.returncode != 0 or not message.get("ok"):
            raise CapabilityExecutionError(
                f"capability execution failed: {message.get('error') or proc.stderr or 'unknown error'}"
            )
        raw = message.get("result")
        if not isinstance(raw, dict):
            raise CapabilityExecutionError("capability execute() must return a dict")
        outputs = dict(raw.get("outputs", raw if "outputs" not in raw else {}))
        missing_outputs = [field for field in manifest.output_fields if field not in outputs]
        if missing_outputs:
            raise CapabilityExecutionError(f"capability result missing declared outputs: {missing_outputs}")
        metadata = dict(raw.get("metadata", {}))
        if "status" in raw:
            # This is only a producer claim; Host verification remains authoritative.
            metadata["capability_claimed_status"] = raw.get("status")
        captured_stdout = message.get("captured_stdout")
        captured_stderr = message.get("captured_stderr")
        if captured_stdout:
            metadata["captured_stdout"] = captured_stdout
        if captured_stderr:
            metadata["captured_stderr"] = captured_stderr
        evidence = list(raw.get("evidence", []))
        artifacts = [str(v) for v in raw.get("artifacts", [])]
        return manifest, outputs, evidence, artifacts, metadata, artifact_dir

    def _execute_readback(self, request: CapabilityRequest) -> CapabilityResult:
        """Execute a registered readback capability without recursively verifying it.

        The readback code must itself be a verified Registry capability. Its
        returned data is evidence for the parent verification check, not a
        trusted final Task Outcome on its own.
        """
        _manifest, outputs, evidence, artifacts, metadata, _artifact_dir = self._run_process(request)
        return CapabilityResult(
            request_id=request.request_id,
            capability_id=request.capability_id,
            status="succeeded",
            process_status="process_completed",
            verification_status="unverified",
            outputs=outputs,
            evidence=evidence,
            artifacts=artifacts,
            metadata=metadata,
            verification={"status": "unverified", "trusted": False, "mode": "readback_probe", "checks": []},
        )

    def execute(self, request: CapabilityRequest) -> CapabilityResult:
        manifest, outputs, evidence, artifacts, metadata, artifact_dir = self._run_process(request)
        verification = self.verification_engine.verify(
            request=request,
            verification_plan=manifest.verification,
            outputs=outputs,
            evidence=evidence,
            artifacts=artifacts,
            artifact_dir=artifact_dir,
            readback_executor=self._execute_readback,
        )
        return CapabilityResult(
            request_id=request.request_id,
            capability_id=request.capability_id,
            status="succeeded",
            process_status="process_completed",
            verification_status=verification.status,
            outputs=outputs,
            evidence=evidence,
            artifacts=artifacts,
            metadata=metadata,
            verification=verification.to_dict(),
        )
