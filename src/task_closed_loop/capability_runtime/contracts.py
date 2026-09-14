from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional


class ContractError(ValueError):
    pass


def _required_text(value: Any, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ContractError(f"{name} is required")
    return text


def _unique_text_list(values: Any, name: str) -> List[str]:
    if values is None:
        return []
    if not isinstance(values, list):
        raise ContractError(f"{name} must be a list")
    result: List[str] = []
    seen = set()
    for raw in values:
        value = _required_text(raw, name)
        if value in seen:
            raise ContractError(f"{name} contains duplicate value: {value}")
        seen.add(value)
        result.append(value)
    return result


@dataclass(frozen=True)
class CapabilityBuildRequest:
    build_id: str
    capability_id: str
    domain: str
    operation: str
    objective: str
    required_inputs: List[str] = field(default_factory=list)
    expected_outputs: List[str] = field(default_factory=list)
    permissions: Dict[str, bool] = field(default_factory=dict)
    secret_refs: List[str] = field(default_factory=list)
    requested_by_task_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    verification: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CapabilityBuildRequest":
        return cls(
            build_id=_required_text(data.get("build_id"), "build_id"),
            capability_id=_required_text(data.get("capability_id"), "capability_id"),
            domain=_required_text(data.get("domain"), "domain"),
            operation=_required_text(data.get("operation"), "operation"),
            objective=_required_text(data.get("objective"), "objective"),
            required_inputs=_unique_text_list(data.get("required_inputs", []), "required_inputs"),
            expected_outputs=_unique_text_list(data.get("expected_outputs", []), "expected_outputs"),
            permissions={str(k): bool(v) for k, v in dict(data.get("permissions", {})).items()},
            secret_refs=_unique_text_list(data.get("secret_refs", []), "secret_refs"),
            requested_by_task_id=(str(data.get("requested_by_task_id")).strip() if data.get("requested_by_task_id") else None),
            metadata=dict(data.get("metadata", {})),
            verification=dict(data.get("verification", {})),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "build_id": self.build_id,
            "capability_id": self.capability_id,
            "domain": self.domain,
            "operation": self.operation,
            "objective": self.objective,
            "required_inputs": list(self.required_inputs),
            "expected_outputs": list(self.expected_outputs),
            "permissions": dict(self.permissions),
            "secret_refs": list(self.secret_refs),
            "requested_by_task_id": self.requested_by_task_id,
            "metadata": dict(self.metadata),
            "verification": dict(self.verification),
        }


@dataclass(frozen=True)
class CapabilityManifest:
    capability_id: str
    version: int
    status: str
    domain: str
    operation: str
    entrypoint_file: str
    entrypoint_function: str = "execute"
    input_fields: List[str] = field(default_factory=list)
    output_fields: List[str] = field(default_factory=list)
    permissions: Dict[str, bool] = field(default_factory=dict)
    secret_refs: List[str] = field(default_factory=list)
    build_id: Optional[str] = None
    created_by_engine: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    verification: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CapabilityManifest":
        implementation = dict(data.get("implementation", {}))
        entrypoint_file = implementation.get("entrypoint_file") or data.get("entrypoint_file")
        entrypoint_function = implementation.get("function") or data.get("entrypoint_function") or "execute"
        version = int(data.get("version", 0))
        if version < 1:
            raise ContractError("version must be >= 1")
        status = _required_text(data.get("status", "draft"), "status")
        if status not in {"draft", "testing", "verified", "enabled", "deprecated", "replaced"}:
            raise ContractError(f"unsupported capability status: {status}")
        return cls(
            capability_id=_required_text(data.get("capability_id"), "capability_id"),
            version=version,
            status=status,
            domain=_required_text(data.get("domain"), "domain"),
            operation=_required_text(data.get("operation"), "operation"),
            entrypoint_file=_required_text(entrypoint_file, "implementation.entrypoint_file"),
            entrypoint_function=_required_text(entrypoint_function, "implementation.function"),
            input_fields=_unique_text_list(data.get("inputs", data.get("input_fields", [])), "inputs"),
            output_fields=_unique_text_list(data.get("outputs", data.get("output_fields", [])), "outputs"),
            permissions={str(k): bool(v) for k, v in dict(data.get("permissions", {})).items()},
            secret_refs=_unique_text_list(data.get("secret_refs", []), "secret_refs"),
            build_id=(str(data.get("build_id")).strip() if data.get("build_id") else None),
            created_by_engine=(str(data.get("created_by_engine")).strip() if data.get("created_by_engine") else None),
            metadata=dict(data.get("metadata", {})),
            verification=dict(data.get("verification", {})),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "version": self.version,
            "status": self.status,
            "domain": self.domain,
            "operation": self.operation,
            "implementation": {
                "entrypoint_file": self.entrypoint_file,
                "function": self.entrypoint_function,
            },
            "inputs": list(self.input_fields),
            "outputs": list(self.output_fields),
            "permissions": dict(self.permissions),
            "secret_refs": list(self.secret_refs),
            "build_id": self.build_id,
            "created_by_engine": self.created_by_engine,
            "metadata": dict(self.metadata),
            "verification": dict(self.verification),
        }


@dataclass(frozen=True)
class CapabilityRequest:
    request_id: str
    capability_id: str
    inputs: Dict[str, Any] = field(default_factory=dict)
    task_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CapabilityRequest":
        return cls(
            request_id=_required_text(data.get("request_id"), "request_id"),
            capability_id=_required_text(data.get("capability_id"), "capability_id"),
            inputs=dict(data.get("inputs", {})),
            task_id=(str(data.get("task_id")).strip() if data.get("task_id") else None),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass(frozen=True)
class CapabilityResult:
    request_id: str
    capability_id: str
    status: str
    outputs: Dict[str, Any] = field(default_factory=dict)
    evidence: List[Dict[str, Any]] = field(default_factory=list)
    artifacts: List[str] = field(default_factory=list)
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    process_status: str = "process_completed"
    verification_status: str = "unverified"
    verification: Dict[str, Any] = field(default_factory=dict)

    @property
    def trusted(self) -> bool:
        return self.process_status == "process_completed" and self.verification_status == "verified"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "capability_id": self.capability_id,
            "status": self.status,
            "process_status": self.process_status,
            "verification_status": self.verification_status,
            "trusted": self.trusted,
            "outputs": dict(self.outputs),
            "evidence": list(self.evidence),
            "artifacts": list(self.artifacts),
            "error": self.error,
            "metadata": dict(self.metadata),
            "verification": dict(self.verification),
        }


@dataclass(frozen=True)
class CapabilityTestResult:
    build_id: str
    status: str
    command: List[str]
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    duration_seconds: float = 0.0
    candidate_checksum: Optional[str] = None

    @property
    def passed(self) -> bool:
        return self.status == "passed" and self.exit_code == 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "build_id": self.build_id,
            "status": self.status,
            "command": list(self.command),
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "duration_seconds": self.duration_seconds,
            "candidate_checksum": self.candidate_checksum,
        }
