from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional

from .contracts import CapabilityRequest, CapabilityResult


@dataclass(frozen=True)
class VerificationCheckResult:
    check_id: str
    check_type: str
    status: str
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "check_id": self.check_id,
            "check_type": self.check_type,
            "status": self.status,
            "message": self.message,
            "details": dict(self.details),
        }


@dataclass(frozen=True)
class VerificationResult:
    status: str
    checks: List[VerificationCheckResult] = field(default_factory=list)
    mode: str = "none"

    @property
    def trusted(self) -> bool:
        return self.status == "verified"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "trusted": self.trusted,
            "mode": self.mode,
            "checks": [check.to_dict() for check in self.checks],
        }


def _deep_get(mapping: Mapping[str, Any], dotted_path: str) -> Any:
    value: Any = mapping
    for segment in str(dotted_path).split("."):
        if not isinstance(value, Mapping) or segment not in value:
            raise KeyError(dotted_path)
        value = value[segment]
    return value


def _resolve_spec(
    spec: Any,
    *,
    request_inputs: Mapping[str, Any],
    outputs: Mapping[str, Any],
    readback_outputs: Optional[Mapping[str, Any]] = None,
) -> Any:
    if not isinstance(spec, Mapping):
        return spec
    source = str(spec.get("source", "literal"))
    if source == "literal":
        return spec.get("value")
    field = str(spec.get("field", "")).strip()
    if not field:
        raise KeyError("verification value spec requires field")
    if source == "input":
        return _deep_get(request_inputs, field)
    if source == "output":
        return _deep_get(outputs, field)
    if source == "readback_output":
        if readback_outputs is None:
            raise KeyError("readback outputs are not available")
        return _deep_get(readback_outputs, field)
    raise KeyError(f"unsupported verification source: {source}")


class ExecutionVerificationEngine:
    """Host-owned verifier.

    Capability/CLI self-reported success is never sufficient. This verifier
    uses only the host-owned verification plan stored in the verified manifest.
    """

    def verify(
        self,
        *,
        request: CapabilityRequest,
        verification_plan: Mapping[str, Any],
        outputs: Mapping[str, Any],
        evidence: List[Dict[str, Any]],
        artifacts: List[str],
        artifact_dir: Path,
        readback_executor: Callable[[CapabilityRequest], CapabilityResult],
    ) -> VerificationResult:
        plan = dict(verification_plan or {})
        checks_raw = plan.get("checks", [])
        if not isinstance(checks_raw, list) or not checks_raw:
            return VerificationResult(status="unverified", checks=[], mode=str(plan.get("mode", "none")))

        results: List[VerificationCheckResult] = []
        for index, raw in enumerate(checks_raw, start=1):
            if not isinstance(raw, Mapping):
                results.append(VerificationCheckResult(
                    check_id=f"check-{index}", check_type="invalid", status="unverified",
                    message="verification check must be a mapping",
                ))
                continue
            check = dict(raw)
            check_id = str(check.get("id") or f"check-{index}")
            check_type = str(check.get("type") or "").strip()
            try:
                if check_type == "output_present":
                    field = str(check["field"])
                    value = _deep_get(outputs, field)
                    passed = value is not None
                    results.append(self._result(check_id, check_type, passed, f"output field {field} is present"))
                elif check_type == "output_equals_input":
                    output_field = str(check["output"])
                    input_field = str(check["input"])
                    actual = _deep_get(outputs, output_field)
                    expected = _deep_get(request.inputs, input_field)
                    results.append(self._compare(check_id, check_type, actual, expected))
                elif check_type == "evidence_min_count":
                    minimum = int(check.get("min_count", 1))
                    actual = len(evidence)
                    results.append(self._result(
                        check_id, check_type, actual >= minimum,
                        f"evidence count {actual}, required >= {minimum}",
                        {"actual": actual, "minimum": minimum},
                    ))
                elif check_type == "artifact_exists":
                    candidate = check.get("path")
                    if "from_output" in check:
                        candidate = _deep_get(outputs, str(check["from_output"]))
                    if candidate is None:
                        raise KeyError("artifact_exists requires path or from_output")
                    path = Path(str(candidate))
                    if not path.is_absolute():
                        path = (artifact_dir / path).resolve()
                    else:
                        path = path.resolve()
                    root = artifact_dir.resolve()
                    inside = path == root or root in path.parents
                    passed = inside and path.exists()
                    results.append(self._result(
                        check_id, check_type, passed,
                        "artifact exists inside request artifact directory" if passed else "artifact missing or outside artifact directory",
                        {"path": str(path), "inside_artifact_dir": inside},
                    ))
                elif check_type == "capability_readback":
                    results.append(self._run_readback_check(
                        check_id=check_id,
                        check=check,
                        request=request,
                        outputs=outputs,
                        readback_executor=readback_executor,
                    ))
                else:
                    results.append(VerificationCheckResult(
                        check_id=check_id, check_type=check_type or "unknown", status="unverified",
                        message=f"unsupported verification check type: {check_type or '<empty>'}",
                    ))
            except Exception as exc:
                results.append(VerificationCheckResult(
                    check_id=check_id, check_type=check_type or "unknown", status="failed",
                    message=f"verification check raised: {exc}",
                ))

        statuses = [result.status for result in results]
        passed = statuses.count("passed")
        failed = statuses.count("failed")
        unknown = statuses.count("unverified")
        if passed == len(statuses):
            status = "verified"
        elif failed == len(statuses):
            status = "failed"
        elif passed > 0 and (failed > 0 or unknown > 0):
            status = "partial"
        elif failed > 0:
            status = "failed"
        else:
            status = "unverified"
        return VerificationResult(status=status, checks=results, mode=str(plan.get("mode", "deterministic")))

    @staticmethod
    def _result(check_id: str, check_type: str, passed: bool, message: str, details: Optional[Dict[str, Any]] = None) -> VerificationCheckResult:
        return VerificationCheckResult(
            check_id=check_id,
            check_type=check_type,
            status="passed" if passed else "failed",
            message=message,
            details=dict(details or {}),
        )

    @staticmethod
    def _compare(check_id: str, check_type: str, actual: Any, expected: Any) -> VerificationCheckResult:
        return VerificationCheckResult(
            check_id=check_id,
            check_type=check_type,
            status="passed" if actual == expected else "failed",
            message="values match" if actual == expected else "values do not match",
            details={"actual": actual, "expected": expected},
        )

    def _run_readback_check(
        self,
        *,
        check_id: str,
        check: Mapping[str, Any],
        request: CapabilityRequest,
        outputs: Mapping[str, Any],
        readback_executor: Callable[[CapabilityRequest], CapabilityResult],
    ) -> VerificationCheckResult:
        capability_id = str(check.get("capability_id") or "").strip()
        if not capability_id:
            raise KeyError("capability_readback requires capability_id")
        bindings = check.get("inputs", {})
        if not isinstance(bindings, Mapping):
            raise TypeError("capability_readback inputs must be a mapping")
        readback_inputs: Dict[str, Any] = {}
        for name, spec in bindings.items():
            readback_inputs[str(name)] = _resolve_spec(
                spec, request_inputs=request.inputs, outputs=outputs
            )
        rb_request = CapabilityRequest(
            request_id=f"{request.request_id}.verify.{check_id}",
            capability_id=capability_id,
            inputs=readback_inputs,
            task_id=request.task_id,
            metadata={"verification_readback": True, "parent_request_id": request.request_id},
        )
        rb_result = readback_executor(rb_request)
        if rb_result.process_status != "process_completed":
            return VerificationCheckResult(
                check_id=check_id, check_type="capability_readback", status="failed",
                message="readback capability did not complete",
                details={"readback_status": rb_result.process_status},
            )
        assertions = check.get("assertions", [])
        if not isinstance(assertions, list) or not assertions:
            return VerificationCheckResult(
                check_id=check_id, check_type="capability_readback", status="unverified",
                message="readback completed but no assertions were defined",
            )
        assertion_results: List[Dict[str, Any]] = []
        all_passed = True
        for raw_assertion in assertions:
            if not isinstance(raw_assertion, Mapping):
                all_passed = False
                assertion_results.append({"status": "failed", "error": "assertion must be a mapping"})
                continue
            actual = _resolve_spec(
                raw_assertion.get("actual"),
                request_inputs=request.inputs,
                outputs=outputs,
                readback_outputs=rb_result.outputs,
            )
            expected = _resolve_spec(
                raw_assertion.get("expected"),
                request_inputs=request.inputs,
                outputs=outputs,
                readback_outputs=rb_result.outputs,
            )
            ok = actual == expected
            all_passed = all_passed and ok
            assertion_results.append({"status": "passed" if ok else "failed", "actual": actual, "expected": expected})
        return VerificationCheckResult(
            check_id=check_id,
            check_type="capability_readback",
            status="passed" if all_passed else "failed",
            message="readback assertions passed" if all_passed else "readback assertions failed",
            details={"readback_capability_id": capability_id, "assertions": assertion_results},
        )
