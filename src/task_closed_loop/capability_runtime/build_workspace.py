from __future__ import annotations

from pathlib import Path
from typing import Dict, Any

from .contracts import CapabilityBuildRequest
from .errors import BuildError
from .io_utils import atomic_write_yaml, read_yaml




def _validate_verification_policy(request: CapabilityBuildRequest) -> None:
    checks = request.verification.get("checks", []) if isinstance(request.verification, dict) else []
    check_types = {str(check.get("type", "")) for check in checks if isinstance(check, dict)}
    if request.permissions.get("external_write", False) and "capability_readback" not in check_types:
        raise BuildError("external_write capability requires host-owned capability_readback verification")
    if request.permissions.get("filesystem_write", False) and not ({"artifact_exists", "capability_readback"} & check_types):
        raise BuildError("filesystem_write capability requires artifact_exists or capability_readback verification")


class BuildWorkspaceManager:
    def __init__(self, builds_root: Path):
        self.builds_root = Path(builds_root).resolve()
        self.builds_root.mkdir(parents=True, exist_ok=True)

    def path_for(self, build_id: str) -> Path:
        if not build_id or any(part in build_id for part in ("/", "\\", "..")):
            raise BuildError("build_id must be a simple path-safe identifier")
        path = (self.builds_root / build_id).resolve()
        if self.builds_root not in path.parents:
            raise BuildError("build path escapes builds root")
        return path

    def create(self, request: CapabilityBuildRequest) -> Path:
        _validate_verification_policy(request)
        path = self.path_for(request.build_id)
        if path.exists():
            raise BuildError(f"build already exists: {request.build_id}")
        (path / "implementation").mkdir(parents=True)
        (path / "tests").mkdir()
        (path / "artifacts").mkdir()
        atomic_write_yaml(path / "build_request.yml", request.to_dict())
        atomic_write_yaml(path / "build_state.yml", {"build_id": request.build_id, "status": "requested"})
        return path


    def reset_candidate(self, build_id: str) -> None:
        import shutil
        path = self.path_for(build_id)
        if not path.exists():
            raise BuildError(f"unknown build: {build_id}")
        for name in ["implementation", "tests", "artifacts"]:
            target = path / name
            if target.exists():
                shutil.rmtree(target)
            target.mkdir()
        for name in ["candidate_manifest.yml", "test_result.yml"]:
            target = path / name
            if target.exists():
                target.unlink()


    def import_candidate_from_stage(self, build_id: str, stage_path: Path) -> None:
        import shutil
        from .candidate_integrity import reject_symlinks

        destination = self.path_for(build_id)
        stage_path = Path(stage_path).resolve()
        allowed_dirs = ["implementation", "tests", "artifacts"]
        allowed_files = ["candidate_manifest.yml"]
        for name in allowed_dirs:
            source = stage_path / name
            if source.exists():
                reject_symlinks(source)
                target = destination / name
                if target.exists():
                    shutil.rmtree(target)
                shutil.copytree(source, target)
            else:
                target = destination / name
                if target.exists():
                    shutil.rmtree(target)
                target.mkdir()
        for name in allowed_files:
            source = stage_path / name
            target = destination / name
            if source.exists():
                if source.is_symlink():
                    raise BuildError(f"symlink candidate file is not allowed: {name}")
                shutil.copy2(source, target)
            elif target.exists():
                target.unlink()

    def set_state(self, build_id: str, status: str, **details: Any) -> None:
        path = self.path_for(build_id)
        if not path.exists():
            raise BuildError(f"unknown build: {build_id}")
        data: Dict[str, Any] = {"build_id": build_id, "status": status}
        data.update(details)
        atomic_write_yaml(path / "build_state.yml", data)

    def load_request(self, build_id: str) -> CapabilityBuildRequest:
        path = self.path_for(build_id) / "build_request.yml"
        if not path.exists():
            raise BuildError(f"build request missing: {build_id}")
        return CapabilityBuildRequest.from_dict(read_yaml(path))
