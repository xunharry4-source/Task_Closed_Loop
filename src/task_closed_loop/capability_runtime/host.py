from __future__ import annotations

from pathlib import Path
import shutil
import tempfile
from typing import Iterable, Optional

from .contracts import CapabilityBuildRequest, CapabilityRequest, CapabilityResult
from .build_prompt import render_build_prompt
from .build_workspace import BuildWorkspaceManager
from .cli import ClaudeCliAdapter, CliEngineAdapter, CliEngineRouter, CodexCliAdapter, GeminiCliAdapter
from .config import ProjectConfig
from .errors import BuildError
from .executor import CapabilityExecutor
from .secrets import DotEnvSecretResolver
from .promoter import CapabilityPromoter
from .registry import CapabilityRegistry
from .test_gate import CapabilityTestGate


class CapabilityProjectHost:
    def __init__(self, root: Path, adapters: Optional[Iterable[CliEngineAdapter]] = None):
        self.config = ProjectConfig.load(Path(root))
        self.registry = CapabilityRegistry(self.config.path("capability_registry"))
        self.builds = BuildWorkspaceManager(self.config.path("builds"))
        self.test_gate = CapabilityTestGate()
        self.promoter = CapabilityPromoter(self.config.path("capabilities"), self.registry)
        self.executor = CapabilityExecutor(
            self.config.root,
            self.registry,
            secret_resolver=DotEnvSecretResolver(self.config.path("secrets_file")),
        )
        allowed = self.config.raw.get("cli", {}).get("allowed_engines", [])
        if adapters is None:
            adapters = [CodexCliAdapter(), GeminiCliAdapter(), ClaudeCliAdapter()]
        self.router = CliEngineRouter(adapters, preferred=list(allowed))

    def create_build(self, request: CapabilityBuildRequest) -> Path:
        return self.builds.create(request)

    def _engine_preference(self) -> list[str]:
        configured = list(self.config.raw.get("cli", {}).get("allowed_engines", []))
        base = [engine for engine in self.router.preferred if engine in self.router.adapters]
        if not base:
            base = [engine for engine in configured if engine in self.router.adapters]
        if not base:
            base = list(self.router.adapters)
        selection_path = self.config.path("state") / "engine_selection.yml"
        inherited = None
        if selection_path.exists():
            from .io_utils import read_yaml
            raw = read_yaml(selection_path)
            inherited = raw.get("preflight_engine") or raw.get("selected_preflight_engine")
        if inherited in base:
            return [inherited] + [engine for engine in base if engine != inherited]
        return base

    def run_cli_build(self, build_id: str, explicit_engine: Optional[str] = None, timeout_seconds: int = 900):
        request = self.builds.load_request(build_id)
        build_path = self.builds.path_for(build_id)
        attempts = []
        engine_ids = [explicit_engine] if explicit_engine else self._engine_preference()
        for engine_id in engine_ids:
            if not engine_id:
                continue
            adapter = self.router.adapters.get(engine_id)
            if not adapter:
                attempts.append({"engine": engine_id, "status": "unknown"})
                continue
            status = adapter.detect()
            if not status.ready:
                attempts.append({"engine": engine_id, "status": status.state})
                if explicit_engine:
                    break
                continue
            self.builds.set_state(build_id, "building", engine=adapter.engine_id, attempts=attempts)
            try:
                # CLI coding happens outside the Execution Project tree so the
                # project-level .env is not an ancestor of the CLI workspace.
                with tempfile.TemporaryDirectory(prefix=f"execution-cli-{build_id}-") as stage_dir_name:
                    stage = Path(stage_dir_name).resolve()
                    for name in ["implementation", "tests", "artifacts"]:
                        (stage / name).mkdir(parents=True, exist_ok=True)
                    shutil.copy2(build_path / "build_request.yml", stage / "build_request.yml")
                    result = adapter.run(mode="build", prompt=render_build_prompt(request), cwd=stage, timeout_seconds=timeout_seconds)
                    if result.succeeded:
                        self.builds.import_candidate_from_stage(build_id, stage)
            except Exception as exc:
                attempts.append({"engine": adapter.engine_id, "status": "error", "detail": str(exc)})
                if explicit_engine:
                    self.builds.set_state(build_id, "failed", engine=adapter.engine_id, attempts=attempts)
                    raise BuildError(f"CLI build failed: {adapter.engine_id}: {exc}") from exc
                self.builds.reset_candidate(build_id)
                continue
            if not result.succeeded:
                attempts.append({"engine": adapter.engine_id, "status": "failed", "exit_code": result.exit_code})
                if explicit_engine:
                    self.builds.set_state(build_id, "failed", engine=adapter.engine_id, attempts=attempts)
                    raise BuildError(f"CLI build failed: {adapter.engine_id}: {result.stderr[-2000:]}")
                self.builds.reset_candidate(build_id)
                continue
            manifest_path = build_path / "candidate_manifest.yml"
            if manifest_path.exists():
                from .io_utils import read_yaml, atomic_write_yaml
                manifest_data = read_yaml(manifest_path)
                manifest_data.setdefault("build_id", build_id)
                manifest_data.setdefault("created_by_engine", adapter.engine_id)
                atomic_write_yaml(manifest_path, manifest_data)
            attempts.append({"engine": adapter.engine_id, "status": "succeeded"})
            self.builds.set_state(build_id, "built", engine=adapter.engine_id, attempts=attempts)
            return result
        self.builds.set_state(build_id, "failed", attempts=attempts)
        raise BuildError(f"no CLI engine could complete build {build_id}: {attempts}")

    def test_build(self, build_id: str):
        build_path = self.builds.path_for(build_id)
        self.builds.set_state(build_id, "testing")
        request = self.builds.load_request(build_id)
        result = self.test_gate.run(build_path, build_id, request=request)
        self.builds.set_state(build_id, "test_passed" if result.passed else "test_failed", exit_code=result.exit_code)
        return result

    def promote_build(self, build_id: str):
        build_path = self.builds.path_for(build_id)
        result_path = build_path / "test_result.yml"
        if not result_path.exists():
            raise BuildError("build has not been tested")
        from .io_utils import read_yaml
        from .contracts import CapabilityTestResult

        raw = read_yaml(result_path)
        result = CapabilityTestResult(
            build_id=raw["build_id"],
            status=raw["status"],
            command=list(raw.get("command", [])),
            exit_code=int(raw.get("exit_code", 1)),
            stdout=str(raw.get("stdout", "")),
            stderr=str(raw.get("stderr", "")),
            duration_seconds=float(raw.get("duration_seconds", 0.0)),
            candidate_checksum=(str(raw.get("candidate_checksum")) if raw.get("candidate_checksum") else None),
        )
        manifest, destination = self.promoter.promote(build_path, result)
        self.builds.set_state(build_id, "promoted", capability_id=manifest.capability_id, version=manifest.version)
        return manifest, destination

    def execute(self, request: CapabilityRequest) -> CapabilityResult:
        return self.executor.execute(request)

# Backward-compatible internal alias for migrated Execution Project tests/code.
ExecutionProjectHost = CapabilityProjectHost
