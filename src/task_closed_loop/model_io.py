"""Names the model sees at the Stage 3-7 boundary.

Internal code (domain dataclasses, lineage checks, dedupe, artifacts) keeps its
historical field names. Those names are jargon to a model: `reality_relation`,
`work_relation`, `effective_existing_tasks` next to `all_existing_tasks`. A model that
cannot tell what a field means guesses, and a guessed reference format is exactly why
valid discoveries were discarded.

So renaming happens only at the edge:

- before a call, internal names are rewritten to the names below;
- after a call, the model's answer is mapped back along the same schema/contract.

Only *structure* is renamed. The contents of opaque values (resource payloads, raw
observations, free-form facts) are user data and are never touched, otherwise a
payload key that happens to be called `focus` would be silently corrupted.

This module lives at the package root, not under `llm/`, because `tasks/` also needs
the model view to resolve references, and `llm/__init__` imports every adapter.
"""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
from typing import Any

# Top-level input sections. One direction only: the model never sends these back.
# The four sections a model can cite share their name with the reference type prefix
# (resources -> resource:, reality -> reality:, ...), so what it sees is what it cites.
INPUT_KEY_MAP: dict[str, str] = {
    "current_resources": "resources",
    "resources": "resources",
    "current_reality": "reality",
    "current_capabilities": "capabilities",
    "task_outcomes": "task_outcomes",
    "effective_existing_tasks": "open_tasks",
    "all_existing_tasks": "all_tasks_history",
    "discovery_signals": "findings",
    "task_seeds": "task_ideas",
    "first_pass_accepted_candidates": "accepted_tasks_so_far",
    "first_pass_rejected_contexts": "rejected_tasks_so_far",
    "coverage_thinking_dimensions": "new_angles",
    "candidate": "task_under_review",
    "task": "task_under_review",
    "candidates": "tasks_under_review",
    "existing_tasks": "tasks_to_recheck",
    "discovery_phase": "step",
}

# Field names inside domain objects and in output schemas. Two directions, so every
# friendly name must be unique. Generic words (description, status, reason, evidence,
# user_value, reality_id, evidence_refs ...) are deliberately absent: they mean
# different things on different objects, and a global rename would cross them
# (Task.status is not a review verdict).
FIELD_MAP: dict[str, str] = {
    "discoveries": "findings",
    "discovery_id": "finding_id",
    "discovery_kind": "finding_type",
    "reality_relation": "what_was_observed",
    "user_relevance_hypothesis": "why_it_matters_to_user",
    "desired_change_or_answer": "desired_outcome",
    "independence_reason": "why_it_is_separate",
    "reality_basis_refs": "based_on_refs",
    "relevant_capability_ids": "related_capability_ids",
    "seeds": "task_ideas",
    "seed_id": "idea_id",
    "work_relation": "work_to_do",
    "result_goal": "target_result",
    "user_value_hypothesis": "expected_user_value",
    "required_capability_ids": "needed_capability_ids",
    "identity_anchor_refs": "about_object_refs",
    "parent_task_ids": "source_task_ids",
    "parent_outcome_ids": "source_outcome_ids",
    "proliferation_reason": "why_follow_up_is_needed",
    "source_discovery_ids": "from_finding_ids",
    "candidates": "tasks",
    "dimension": "problem_area",
    "solutions": "possible_directions",
    "how_created": "how_to_create_it",
    "task_identity": "task_key",
    "reality_basis": "basis_explanation",
    "expected_reality_result": "expected_result",
    "execution_steps": "steps",
    "dimensions": "new_angles",
    "dimension_id": "angle_id",
    "focus": "angle",
    "user_question": "question_to_answer",
    "value_reason": "why_valuable",
    "core_valid": "is_valid_work",
    "repair_required": "needs_rewrite",
    "field_issues": "wording_problems",
    "keep_candidate_ids": "keep_ids",
    "effective_task_ids": "still_open_task_ids",
    "replaced_task_ids": "superseded_task_ids",
    "current_facts": "facts",
    "current_gaps": "gaps",
    "current_conflicts": "conflicts",
    "identity_relations": "object_relations",
}

REVERSE_FIELD_MAP: dict[str, str] = {friendly: internal for internal, friendly in FIELD_MAP.items()}

if len(REVERSE_FIELD_MAP) != len(FIELD_MAP):
    raise RuntimeError("model_io.FIELD_MAP friendly names must be unique.")
if set(FIELD_MAP.values()) & set(FIELD_MAP):
    raise RuntimeError("model_io.FIELD_MAP friendly names must not reuse an internal name.")

# Values under these internal keys are user/observed data, not structure.
OPAQUE_VALUE_KEYS = frozenset(
    {
        "payload",
        "raw_observation",
        "raw_result",
        "discovery_payload",
        "input_schema",
        "target_scope",
        "observation_target_scope",
        "current_facts",
        "identity_relations",
        "config",
        "scope",
        "directory_structure",
        "data_summary",
        "content_summary",
        "observed_data_summary",
    }
)

REFERENCE_FORMS = (
    "resource:<resource_id>[#字段路径]、reality:current[#字段路径]、"
    "task_outcome:<outcome_id>[#字段路径]、capability:<capability_id>、"
    "或输入中声明过的观察对象原样（例如 gmail:message:abc）"
)

REF_FIELD_DESCRIPTIONS: dict[str, str] = {
    "based_on_refs": (
        "本条内容所依据的输入对象。每一项必须是以下写法之一："
        + REFERENCE_FORMS
        + "。字段路径用 # 与身份分隔；路径内用 . 分隔键、用 [n] 表示下标，"
        "并且必须真实存在于你在输入里看到的那个对象中。"
    ),
    "about_object_refs": (
        "本任务针对的稳定对象。只能是 task_outcomes 中声明过的 subject_refs 原样，"
        "或 resource:<resource_id>（不带字段路径）。"
    ),
}

REF_FIELD_EXAMPLES: dict[str, list[str]] = {
    "based_on_refs": [
        "resource:<resource_id>#<字段路径>",
        "reality:current#<字段路径>",
    ],
    "about_object_refs": [
        "<task_outcomes 中声明的 subject_ref 原样> 或 resource:<resource_id>",
    ],
}


def to_plain(value: Any) -> Any:
    """Convert domain objects into JSON-compatible plain data."""

    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: to_plain(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Enum):
        return to_plain(value.value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {str(key): to_plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [to_plain(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _rename_structure(value: Any, *, opaque: bool = False) -> Any:
    if opaque:
        return value
    if isinstance(value, dict):
        renamed: dict[str, Any] = {}
        for key, item in value.items():
            name = str(key)
            renamed[FIELD_MAP.get(name, name)] = _rename_structure(
                item, opaque=name in OPAQUE_VALUE_KEYS
            )
        return renamed
    if isinstance(value, list):
        return [_rename_structure(item) for item in value]
    return value


def to_model_view(value: Any) -> Any:
    """A single object exactly as the model sees it inside its input."""

    return _rename_structure(to_plain(value))


def to_model_input(payload: Any) -> Any:
    """The whole input payload, with section names and object fields renamed."""

    plain = to_plain(payload)
    if not isinstance(plain, dict):
        return _rename_structure(plain)
    renamed: dict[str, Any] = {}
    for key, item in plain.items():
        name = str(key)
        target = INPUT_KEY_MAP.get(name) or FIELD_MAP.get(name, name)
        renamed[target] = _rename_structure(item, opaque=name in OPAQUE_VALUE_KEYS)
    return renamed


def to_model_schema(schema: Any) -> Any:
    """Rename a JSON schema's declared properties and describe reference fields."""

    if isinstance(schema, list):
        return [to_model_schema(item) for item in schema]
    if not isinstance(schema, dict):
        return schema

    converted: dict[str, Any] = {}
    for key, value in schema.items():
        if key == "properties" and isinstance(value, dict):
            properties: dict[str, Any] = {}
            for prop_name, prop_schema in value.items():
                friendly = FIELD_MAP.get(str(prop_name), str(prop_name))
                prop = to_model_schema(prop_schema)
                if friendly in REF_FIELD_DESCRIPTIONS and isinstance(prop, dict):
                    prop = {**prop, "description": REF_FIELD_DESCRIPTIONS[friendly]}
                properties[friendly] = prop
            converted[key] = properties
        elif key == "required" and isinstance(value, list):
            converted[key] = [FIELD_MAP.get(str(item), item) for item in value]
        else:
            converted[key] = to_model_schema(value)
    return converted


def to_model_contract(contract: Any) -> Any:
    """Rename an example-shaped response contract (Ollama-family adapters)."""

    if isinstance(contract, list):
        return [to_model_contract(item) for item in contract]
    if not isinstance(contract, dict):
        return contract
    converted: dict[str, Any] = {}
    for key, value in contract.items():
        friendly = FIELD_MAP.get(str(key), str(key))
        if friendly in REF_FIELD_EXAMPLES:
            converted[friendly] = list(REF_FIELD_EXAMPLES[friendly])
        else:
            converted[friendly] = to_model_contract(value)
    return converted


def from_model_output_schema(output: Any, schema: Any) -> Any:
    """Map a model answer back to internal names along its (friendly) JSON schema.

    Only keys the schema declares are renamed; free-form objects are left as they are.
    A model that answered with internal names anyway still parses, because unknown
    keys are kept unchanged.
    """

    if not isinstance(schema, dict):
        return output
    properties = schema.get("properties")
    if isinstance(properties, dict) and isinstance(output, dict):
        restored: dict[str, Any] = {}
        for key, item in output.items():
            if key in properties:
                restored[REVERSE_FIELD_MAP.get(key, key)] = from_model_output_schema(
                    item, properties[key]
                )
            else:
                restored[key] = item
        return restored
    items = schema.get("items")
    if isinstance(items, dict) and isinstance(output, list):
        return [from_model_output_schema(item, items) for item in output]
    return output


def from_model_output_contract(output: Any, contract: Any) -> Any:
    """Map a model answer back to internal names along an example-shaped contract."""

    if isinstance(contract, dict) and isinstance(output, dict):
        restored: dict[str, Any] = {}
        for key, item in output.items():
            if key in contract:
                restored[REVERSE_FIELD_MAP.get(key, key)] = from_model_output_contract(
                    item, contract[key]
                )
            else:
                restored[key] = item
        return restored
    if isinstance(contract, list) and contract and isinstance(output, list):
        return [from_model_output_contract(item, contract[0]) for item in output]
    return output
