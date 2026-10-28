"""Output shapes and parsing for the first-step chain, shared by both adapter families.

The JSON-schema family (gemini / gemma / codex_cli / gemini_cli / lmstudio) and the
example-contract family (ollama / openai / deepseek) need the same fields in two
notations, and the same parsing afterwards. Keeping both here means a field is declared
once, and `model_io` renames it at the boundary exactly as it does for every other role.

Field names are the internal ones on purpose: `reality_basis_refs`, `work_relation`,
`execution_steps` ... `model_io.FIELD_MAP` turns them into the names the model reads
(`based_on_refs`, `work_to_do`, `steps`) and turns the answer back.
"""

from __future__ import annotations

from typing import Any

from task_closed_loop.tasks.models import TaskCandidate
from task_closed_loop.tasks.skill_chain_models import (
    DEMAND_LEVELS,
    PROBLEM_LEVELS,
    VALUE_LEVELS,
    DemandRecord,
    ProblemRecord,
    ThemePlan,
    ValueRecord,
)

_STRING_ARRAY = {"type": "array", "items": {"type": "string"}}


def _object(properties: dict[str, Any]) -> dict[str, Any]:
    # Codex validates with strict structured outputs: every property required,
    # additionalProperties false (see llm/codex_cli.is_strict_schema).
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


# --- JSON schema family -----------------------------------------------------

PROJECT_SCHEMA = _object(
    {
        "projects": {
            "type": "array",
            "items": _object(
                {
                    "project_id": {"type": "string"},
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "resource_ids": _STRING_ARRAY,
                }
            ),
        }
    }
)

PROJECT_CONTRACT = {
    "projects": [
        {
            "project_id": "string",
            "name": "string",
            "description": "string",
            "resource_ids": ["string"],
        }
    ]
}


_ASSIGNED_PROJECT_SCHEMA = _object(
    {"project_id": {"type": "string"}, "note": {"type": "string"}}
)
ASSIGNMENT_SCHEMA = _object(
    {
        "assignments": {
            "type": "array",
            "items": _object(
                {
                    "resource_id": {"type": "string"},
                    "projects": {"type": "array", "items": _ASSIGNED_PROJECT_SCHEMA},
                }
            ),
        }
    }
)

ASSIGNMENT_CONTRACT = {
    "assignments": [
        {
            "resource_id": "string",
            "projects": [{"project_id": "string", "note": "string"}],
        }
    ]
}


PROBLEM_ITEM_SCHEMA = _object(
    {
        "problem_id": {"type": "string"},
        "title": {"type": "string"},
        "problem_level": {"type": "string", "enum": list(PROBLEM_LEVELS)},
        "root_cause": {"type": "string"},
        "dimension": {"type": "string"},
        "severity": {"type": "integer"},
        "economic_impact": {"type": "string"},
        "solutions": {"type": "string"},
        "reality_basis_refs": _STRING_ARRAY,
        "note": {"type": "string"},
    }
)
PROBLEMS_SCHEMA = _object({"problems": {"type": "array", "items": PROBLEM_ITEM_SCHEMA}})

VALUE_ITEM_SCHEMA = _object(
    {
        "value_id": {"type": "string"},
        "title": {"type": "string"},
        "value_level": {"type": "string", "enum": list(VALUE_LEVELS)},
        "value_type": {"type": "string"},
        "value_score": {"type": "integer"},
        "economic_value": {"type": "string"},
        "how_created": {"type": "string"},
        "resources_used": _STRING_ARRAY,
        "capabilities_used": _STRING_ARRAY,
        "reality_basis_refs": _STRING_ARRAY,
        "note": {"type": "string"},
    }
)
VALUES_SCHEMA = _object(
    {"value_opportunities": {"type": "array", "items": VALUE_ITEM_SCHEMA}}
)

DEMAND_ITEM_SCHEMA = _object(
    {
        "demand_id": {"type": "string"},
        "title": {"type": "string"},
        "demand_level": {"type": "string", "enum": list(DEMAND_LEVELS)},
        "required_capability": {"type": "string"},
        "pain_point_evidence": {"type": "string"},
        "reality_basis_refs": _STRING_ARRAY,
    }
)
DEMANDS_SCHEMA = _object(
    {"capability_voids": {"type": "array", "items": DEMAND_ITEM_SCHEMA}}
)

_THEME_ITEM_SCHEMA = _object(
    {
        "theme": {"type": "string"},
        "reason": {"type": "string"},
        # Which problem / value / demand records this theme covers. Tasks generated
        # under the theme inherit their lineage from here, because the task step only
        # sees resources, functions, the project and the theme.
        "source_refs": _STRING_ARRAY,
    }
)
THEME_PLAN_SCHEMA = _object(
    {
        "resource_info": {"type": "string"},
        "themes": {"type": "array", "items": _THEME_ITEM_SCHEMA},
        "skipped_fixed_themes": {"type": "array", "items": _THEME_ITEM_SCHEMA},
    }
)

THEME_CANDIDATE_SCHEMA = _object(
    {
        "task_identity": {"type": "string"},
        "description": {"type": "string"},
        "work_relation": {"type": "string"},
        "reality_basis": {"type": "string"},
        "reality_basis_refs": _STRING_ARRAY,
        "identity_anchor_refs": _STRING_ARRAY,
        "expected_reality_result": {"type": "string"},
        "deliverable": {"type": "string"},
        "user_value": {"type": "string"},
        "execution_steps": _STRING_ARRAY,
        "needed_functions": _STRING_ARRAY,
    }
)
THEME_TASKS_SCHEMA = _object(
    {"candidates": {"type": "array", "items": THEME_CANDIDATE_SCHEMA}}
)


# --- example-contract family ------------------------------------------------

PROBLEMS_CONTRACT = {
    "problems": [
        {
            "problem_id": "string",
            "title": "string",
            "problem_level": "UNKNOWN_BLINDSPOT|KNOWN_DEFECT",
            "root_cause": "string",
            "dimension": "string",
            "severity": "integer 1-5",
            "economic_impact": "string",
            "solutions": "string",
            "reality_basis_refs": ["string"],
            "note": "string",
        }
    ]
}

VALUES_CONTRACT = {
    "value_opportunities": [
        {
            "value_id": "string",
            "title": "string",
            "value_level": "NOVEL_PARADIGM|INCREMENTAL_SCHEME",
            "value_type": "string",
            "value_score": "integer 1-5",
            "economic_value": "string",
            "how_created": "string",
            "resources_used": ["string"],
            "capabilities_used": ["string"],
            "reality_basis_refs": ["string"],
            "note": "string",
        }
    ]
}

DEMANDS_CONTRACT = {
    "capability_voids": [
        {
            "demand_id": "string",
            "title": "string",
            "demand_level": "BREAKTHROUGH_NEED|BASELINE_NEED",
            "required_capability": "string",
            "pain_point_evidence": "string",
            "reality_basis_refs": ["string"],
        }
    ]
}

THEME_PLAN_CONTRACT = {
    "resource_info": "string",
    "themes": [{"theme": "string", "reason": "string", "source_refs": ["string"]}],
    "skipped_fixed_themes": [{"theme": "string", "reason": "string"}],
}

THEME_TASKS_CONTRACT = {
    "candidates": [
        {
            "task_identity": "string",
            "description": "string",
            "work_relation": "string",
            "reality_basis": "string",
            "reality_basis_refs": ["string"],
            "identity_anchor_refs": ["string"],
            "expected_reality_result": "string",
            "deliverable": "string",
            "user_value": "string",
            "execution_steps": ["string"],
            "needed_functions": ["string"],
        }
    ]
}


# --- parsing ----------------------------------------------------------------


def _text(value: Any) -> str:
    return str(value or "").strip()


def _refs(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(_text(item) for item in value if _text(item))


def _score(value: Any, default: int = 3) -> int:
    try:
        return max(1, min(5, int(value)))
    except (TypeError, ValueError):
        return default


def _items(parsed: Any, key: str) -> list[dict[str, Any]]:
    if not isinstance(parsed, dict):
        return []
    raw = parsed.get(key) or []
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def projects_from_payload(parsed: Any) -> list[dict[str, Any]]:
    """The projects the analysis found, with the resources each is based on."""

    out: list[dict[str, Any]] = []
    for item in _items(parsed, "projects"):
        name = _text(item.get("name"))
        resource_ids = _refs(item.get("resource_ids"))
        if not name or not resource_ids:
            continue
        out.append(
            {
                "project_id": _text(item.get("project_id")),
                "name": name,
                "description": _text(item.get("description")),
                "resource_ids": list(resource_ids),
            }
        )
    return out


def assignments_from_payload(parsed: Any) -> dict[str, tuple[tuple[str, str], ...]]:
    """resource_id -> ((project_id, note), ...). A resource may belong to several."""

    out: dict[str, tuple[tuple[str, str], ...]] = {}
    for item in _items(parsed, "assignments"):
        resource_id = _text(item.get("resource_id"))
        if not resource_id:
            continue
        owners: list[tuple[str, str]] = []
        raw = item.get("projects") or []
        if isinstance(raw, list):
            for entry in raw:
                if isinstance(entry, str):
                    entry = {"project_id": entry}
                if not isinstance(entry, dict):
                    continue
                project_id = _text(entry.get("project_id"))
                if project_id and project_id not in [owner[0] for owner in owners]:
                    owners.append((project_id, _text(entry.get("note"))))
        out[resource_id] = tuple(owners)
    return out


def problems_from_payload(parsed: Any) -> list[ProblemRecord]:
    out: list[ProblemRecord] = []
    for index, item in enumerate(_items(parsed, "problems"), start=1):
        title = _text(item.get("title"))
        level = _text(item.get("problem_level")).upper()
        if not title or level not in PROBLEM_LEVELS:
            continue
        out.append(
            ProblemRecord(
                problem_id=_text(item.get("problem_id")) or f"problem-{index}",
                title=title,
                problem_level=level,
                root_cause=_text(item.get("root_cause")),
                dimension=_text(item.get("dimension")),
                severity=_score(item.get("severity")),
                economic_impact=_text(item.get("economic_impact")),
                solutions=_text(item.get("solutions")),
                reality_basis_refs=_refs(item.get("reality_basis_refs")),
                note=_text(item.get("note")),
            )
        )
    return out


def values_from_payload(parsed: Any) -> list[ValueRecord]:
    out: list[ValueRecord] = []
    for index, item in enumerate(_items(parsed, "value_opportunities"), start=1):
        title = _text(item.get("title"))
        level = _text(item.get("value_level")).upper()
        if not title or level not in VALUE_LEVELS:
            continue
        out.append(
            ValueRecord(
                value_id=_text(item.get("value_id")) or f"value-{index}",
                title=title,
                value_level=level,
                value_type=_text(item.get("value_type")),
                value_score=_score(item.get("value_score")),
                economic_value=_text(item.get("economic_value")),
                how_created=_text(item.get("how_created")),
                resources_used=_refs(item.get("resources_used")),
                capabilities_used=_refs(item.get("capabilities_used")),
                reality_basis_refs=_refs(item.get("reality_basis_refs")),
                note=_text(item.get("note")),
            )
        )
    return out


def demands_from_payload(parsed: Any) -> list[DemandRecord]:
    out: list[DemandRecord] = []
    for index, item in enumerate(_items(parsed, "capability_voids"), start=1):
        title = _text(item.get("title"))
        level = _text(item.get("demand_level")).upper()
        if not title or level not in DEMAND_LEVELS:
            continue
        out.append(
            DemandRecord(
                demand_id=_text(item.get("demand_id")) or f"demand-{index}",
                title=title,
                demand_level=level,
                required_capability=_text(item.get("required_capability")),
                pain_point_evidence=_text(item.get("pain_point_evidence")),
                reality_basis_refs=_refs(item.get("reality_basis_refs")),
            )
        )
    return out


def theme_plan_from_payload(parsed: Any) -> ThemePlan:
    def entries(key: str, *, with_sources: bool) -> tuple[dict[str, Any], ...]:
        out: list[dict[str, Any]] = []
        for item in _items(parsed, key):
            theme = _text(item.get("theme"))
            if not theme:
                continue
            entry: dict[str, Any] = {"theme": theme, "reason": _text(item.get("reason"))}
            if with_sources:
                entry["source_refs"] = list(_refs(item.get("source_refs")))
            out.append(entry)
        return tuple(out)

    parsed_dict = parsed if isinstance(parsed, dict) else {}
    return ThemePlan(
        resource_info=_text(parsed_dict.get("resource_info")),
        themes=entries("themes", with_sources=True),
        skipped_fixed_themes=entries("skipped_fixed_themes", with_sources=False),
    )


def theme_tasks_from_payload(parsed: Any) -> list[TaskCandidate]:
    """The tasks of one theme.

    They carry no lineage of their own: this step only sees resources, functions, the
    project and the theme, so the Host attaches the theme's source record afterwards.
    """

    out: list[TaskCandidate] = []
    for item in _items(parsed, "candidates"):
        user_value = _text(item.get("user_value"))
        steps = item.get("execution_steps") or []
        if not user_value or not isinstance(steps, list):
            continue
        steps = tuple(_text(step) for step in steps if _text(step))
        if not steps:
            continue
        metadata: dict[str, Any] = {}
        deliverable = _text(item.get("deliverable"))
        if deliverable:
            metadata["deliverable"] = deliverable
        # The model answers with function names; the Host decides later what that means
        # in terms of concrete capability ids.
        needed_functions = _refs(item.get("needed_functions"))
        if needed_functions:
            metadata["needed_functions"] = list(needed_functions)
        candidate = TaskCandidate(
            task_identity=_text(item.get("task_identity")),
            # reality_id is assigned by the Host: one project, one reality.
            reality_id="",
            description=_text(item.get("description")),
            reality_basis=_text(item.get("reality_basis")),
            expected_reality_result=_text(item.get("expected_reality_result")),
            user_value=user_value,
            execution_steps=steps,
            metadata=metadata,
            work_relation=_text(item.get("work_relation")),
            reality_basis_refs=_refs(item.get("reality_basis_refs")),
            identity_anchor_refs=_refs(item.get("identity_anchor_refs")),
        )
        out.append(candidate)
    return out
