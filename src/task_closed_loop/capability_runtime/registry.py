from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional

from .contracts import CapabilityManifest
from .errors import RegistryError
from .io_utils import atomic_write_yaml, read_yaml


class CapabilityRegistry:
    def __init__(self, path: Path):
        self.path = Path(path)

    def _load(self) -> Dict[str, Any]:
        if not self.path.exists():
            return {"schema_version": 1, "capabilities": []}
        data = read_yaml(self.path)
        entries = data.get("capabilities", [])
        if not isinstance(entries, list):
            raise RegistryError("capability_registry.yml capabilities must be a list")
        seen = set()
        for entry in entries:
            key = (str(entry.get("capability_id")), int(entry.get("version", 0)))
            if key in seen:
                raise RegistryError(f"duplicate registry entry: {key[0]} v{key[1]}")
            seen.add(key)
        return data

    def list(self) -> List[Dict[str, Any]]:
        return deepcopy(self._load().get("capabilities", []))

    def find(self, capability_id: str, version: Optional[int] = None) -> Optional[Dict[str, Any]]:
        matches = [e for e in self._load().get("capabilities", []) if e.get("capability_id") == capability_id]
        if version is not None:
            for entry in matches:
                if int(entry.get("version", 0)) == version:
                    return deepcopy(entry)
            return None
        usable = [e for e in matches if e.get("status") in {"verified", "enabled"}]
        if not usable:
            return None
        return deepcopy(sorted(usable, key=lambda e: int(e.get("version", 0)), reverse=True)[0])

    def register(self, manifest: CapabilityManifest, implementation_path: str, checksum: str) -> Dict[str, Any]:
        if manifest.status not in {"verified", "enabled"}:
            raise RegistryError("only verified/enabled capabilities can be registered")
        data = self._load()
        key = (manifest.capability_id, manifest.version)
        for existing in data.get("capabilities", []):
            if (existing.get("capability_id"), int(existing.get("version", 0))) == key:
                raise RegistryError(f"capability already registered: {manifest.capability_id} v{manifest.version}")
        entry = manifest.to_dict()
        entry["implementation_path"] = implementation_path
        entry["checksum"] = checksum
        data.setdefault("capabilities", []).append(entry)
        atomic_write_yaml(self.path, data)
        return deepcopy(entry)
