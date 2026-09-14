from __future__ import annotations

from .contracts import CapabilityBuildRequest


def render_build_prompt(request: CapabilityBuildRequest) -> str:
    return f"""You are implementing one reusable capability inside an Execution Project build workspace.

HARD BOUNDARIES:
- Work only inside the current build workspace.
- Do not modify the host architecture, contracts, registry, or files outside this build workspace.
- Never write secret values into source code, tests, manifests, logs, fixtures, process environment variables, or shell exports.
- Real secret values are stored by the host in the project .env file. You receive only secret_ref names while coding.
- Capability code must obtain declared secrets from context["secrets"] at runtime; do not read .env directly and do not call os.environ for external-system credentials.
- The host, not you, runs the promotion step.
- The host, not you, marks capabilities verified.

BUILD REQUEST:
- build_id: {request.build_id}
- capability_id: {request.capability_id}
- domain: {request.domain}
- operation: {request.operation}
- objective: {request.objective}
- required_inputs: {request.required_inputs}
- expected_outputs: {request.expected_outputs}
- permissions: {request.permissions}
- secret_refs: {request.secret_refs}
- verification: {request.verification}

CREATE EXACTLY THESE BUILD ASSETS:
1. implementation/main.py with function execute(inputs: dict, context: dict) -> dict.
2. tests/test_capability.py using Python unittest. Tests must import implementation/main.py from this build workspace and require no real secrets or destructive external actions.
3. candidate_manifest.yml with status: testing, version >= 1, entrypoint_file: main.py, function: execute, declared inputs/outputs/permissions/secret_refs and the exact host-provided verification plan.

The execute function must return a dict. For successful execution it should use keys such as outputs, evidence, artifacts, metadata. Raise an exception on execution failure rather than pretending success.

Do not promote or register the capability yourself. Finish only after the files above are complete.
"""
