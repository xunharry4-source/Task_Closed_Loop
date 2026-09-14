from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from .contracts import CapabilityBuildRequest, CapabilityManifest, CapabilityTestResult
from .candidate_integrity import candidate_checksum, reject_symlinks
from .errors import BuildError
from .io_utils import atomic_write_yaml, read_yaml


class CapabilityTestGate:
    def validate_candidate(self, build_path: Path, request: CapabilityBuildRequest | None = None) -> CapabilityManifest:
        manifest_path = build_path / "candidate_manifest.yml"
        if not manifest_path.exists():
            raise BuildError("candidate_manifest.yml is missing")
        manifest = CapabilityManifest.from_dict(read_yaml(manifest_path))
        if manifest.status != "testing":
            raise BuildError("candidate manifest must have status: testing before promotion")
        if request is not None:
            if manifest.capability_id != request.capability_id:
                raise BuildError("candidate capability_id does not match build request")
            if manifest.domain != request.domain:
                raise BuildError("candidate domain does not match build request")
            if manifest.operation != request.operation:
                raise BuildError("candidate operation does not match build request")
            if set(manifest.input_fields) != set(request.required_inputs):
                raise BuildError("candidate inputs do not match build request")
            if set(manifest.output_fields) != set(request.expected_outputs):
                raise BuildError("candidate outputs do not match build request")
            if set(manifest.secret_refs) != set(request.secret_refs):
                raise BuildError("candidate secret_refs do not match build request")
            if manifest.verification != request.verification:
                raise BuildError("candidate verification plan does not match host build request")
            for permission, value in manifest.permissions.items():
                if value and not request.permissions.get(permission, False):
                    raise BuildError(f"candidate escalates undeclared permission: {permission}")
            for permission, value in request.permissions.items():
                if bool(manifest.permissions.get(permission, False)) != bool(value):
                    raise BuildError(f"candidate permission does not match build request: {permission}")
            if manifest.build_id and manifest.build_id != request.build_id:
                raise BuildError("candidate build_id does not match build request")

        implementation_root = (build_path / "implementation").resolve()
        reject_symlinks(implementation_root)
        entrypoint = (implementation_root / manifest.entrypoint_file).resolve()
        if implementation_root not in entrypoint.parents and entrypoint != implementation_root:
            raise BuildError("candidate entrypoint escapes implementation directory")
        if not entrypoint.exists() or not entrypoint.is_file():
            raise BuildError(f"candidate entrypoint missing: {entrypoint}")
        test_dir = (build_path / "tests").resolve()
        reject_symlinks(test_dir)
        if not list(test_dir.glob("test_*.py")):
            raise BuildError("candidate must include at least one test_*.py")
        return manifest

    def run(self, build_path: Path, build_id: str, request: CapabilityBuildRequest | None = None, timeout_seconds: int = 300) -> CapabilityTestResult:
        self.validate_candidate(build_path, request=request)
        command = [sys.executable, "-I", "-m", "unittest", "discover", "-s", str(build_path / "tests"), "-p", "test_*.py"]
        env = {
            "PATH": os.environ.get("PATH", ""),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONIOENCODING": "utf-8",
            "EXECUTION_PROJECT_BUILD_ROOT": str(build_path),
            "EXECUTION_PROJECT_TEST_MODE": "1",
        }
        started = time.monotonic()
        proc = subprocess.run(
            command,
            cwd=str(build_path),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            encoding="utf-8",
            errors="replace",
        )
        duration = time.monotonic() - started
        checksum = candidate_checksum(build_path)
        result = CapabilityTestResult(
            build_id=build_id,
            status="passed" if proc.returncode == 0 else "failed",
            command=command,
            exit_code=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
            duration_seconds=duration,
            candidate_checksum=checksum,
        )
        atomic_write_yaml(build_path / "test_result.yml", result.to_dict())
        return result
