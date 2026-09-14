from __future__ import annotations

import hashlib
import shutil
from dataclasses import replace
from pathlib import Path
from typing import Tuple

from .contracts import CapabilityManifest, CapabilityTestResult
from .errors import PromotionError
from .candidate_integrity import candidate_checksum
from .io_utils import atomic_write_yaml, read_yaml
from .registry import CapabilityRegistry


def _tree_checksum(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file() and "__pycache__" not in p.parts):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


class CapabilityPromoter:
    def __init__(self, capabilities_root: Path, registry: CapabilityRegistry):
        self.capabilities_root = Path(capabilities_root).resolve()
        self.registry = registry

    def promote(self, build_path: Path, test_result: CapabilityTestResult) -> Tuple[CapabilityManifest, Path]:
        if not test_result.passed:
            raise PromotionError("cannot promote a build whose tests did not pass")
        if not test_result.candidate_checksum:
            raise PromotionError("tested candidate checksum is missing")
        current_checksum = candidate_checksum(build_path)
        if current_checksum != test_result.candidate_checksum:
            raise PromotionError("candidate changed after tests passed; re-test is required")
        manifest_path = build_path / "candidate_manifest.yml"
        if not manifest_path.exists():
            raise PromotionError("candidate_manifest.yml missing")
        candidate = CapabilityManifest.from_dict(read_yaml(manifest_path))
        if candidate.status != "testing":
            raise PromotionError("candidate manifest must be in testing state")
        if candidate.build_id and candidate.build_id != test_result.build_id:
            raise PromotionError("candidate build_id does not match tested build")

        destination = (self.capabilities_root / candidate.domain / candidate.capability_id / f"v{candidate.version}").resolve()
        if self.capabilities_root not in destination.parents:
            raise PromotionError("capability destination escapes capabilities root")
        if destination.exists():
            raise PromotionError(f"capability version already exists: {candidate.capability_id} v{candidate.version}")
        destination.mkdir(parents=True, exist_ok=False)
        shutil.copytree(build_path / "implementation", destination / "implementation")

        verified = replace(candidate, status="verified", build_id=test_result.build_id)
        atomic_write_yaml(destination / "manifest.yml", verified.to_dict())
        checksum = _tree_checksum(destination)
        implementation_path = str(destination.relative_to(self.capabilities_root.parent).as_posix())
        self.registry.register(verified, implementation_path=implementation_path, checksum=checksum)
        return verified, destination
