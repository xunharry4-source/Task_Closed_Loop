"""Stage 3 first-step records: project -> problem / value / demand -> task.

The production chain is `数据源/功能 → 项目(实体) → 问题/价值/需求 → 任务`. Every task
must come from one of the three middle-layer records of the *same* project, so these
records are first-class objects with their own identity, not free-text findings that
disappear when the run ends.

Field names reuse the existing internal vocabulary wherever the concept already exists
(`reality_basis_refs`, `identity_anchor_refs`, `required_capability_ids`, ...), so the
model boundary in `model_io` renames them exactly as it does everywhere else.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Middle-layer levels. The level decides the task tier, so it is a closed set.
UNKNOWN_BLINDSPOT = "UNKNOWN_BLINDSPOT"
KNOWN_DEFECT = "KNOWN_DEFECT"
PROBLEM_LEVELS = (UNKNOWN_BLINDSPOT, KNOWN_DEFECT)

NOVEL_PARADIGM = "NOVEL_PARADIGM"
INCREMENTAL_SCHEME = "INCREMENTAL_SCHEME"
VALUE_LEVELS = (NOVEL_PARADIGM, INCREMENTAL_SCHEME)

BREAKTHROUGH_NEED = "BREAKTHROUGH_NEED"
BASELINE_NEED = "BASELINE_NEED"
DEMAND_LEVELS = (BREAKTHROUGH_NEED, BASELINE_NEED)

# Source tables, as the task store (and its triggers) name them.
SOURCE_PROBLEMS = "problems"
SOURCE_VALUES = "value_opportunities"
SOURCE_DEMANDS = "capability_voids"

SOURCE_KIND_TO_TABLE = {
    "problem": SOURCE_PROBLEMS,
    "value": SOURCE_VALUES,
    "demand": SOURCE_DEMANDS,
}

# Themes. The five fixed ones are supplied by the Host, never invented by the model,
# and 探针 / 破局 are never skipped.
THEME_OPTIMIZATION = "优化"
THEME_PROGRESS = "推进"
THEME_REVENUE = "收益"
THEME_PROBE = "探针"
THEME_PARADIGM = "破局"
FIXED_THEMES = (
    THEME_OPTIMIZATION,
    THEME_PROGRESS,
    THEME_REVENUE,
    THEME_PROBE,
    THEME_PARADIGM,
)
UNSKIPPABLE_THEMES = (THEME_PROBE, THEME_PARADIGM)

THEME_KIND_FIXED = "固定"
THEME_KIND_DERIVED = "推导"

TIER_1 = "TIER_1_BREAKTHROUGH"
TIER_2 = "TIER_2_BASELINE"

TASK_TYPE_UNKNOWN_PROBE = "UNKNOWN_PROBE"
TASK_TYPE_NEW_PARADIGM = "NEW_PARADIGM"
TASK_TYPE_FIX_AUDIT = "FIX_AUDIT"
TASK_TYPE_CREATIVE_PROGRESS = "CREATIVE_PROGRESS"
TASK_TYPE_DECISION_ANALYSIS = "DECISION_ANALYSIS"
TASK_TYPE_MECHANISM_ITERATION = "MECHANISM_ITERATION"

# Theme -> baseline task type. Probe/paradigm themes are tier 1 and handled separately.
THEME_TASK_TYPES = {
    THEME_OPTIMIZATION: TASK_TYPE_FIX_AUDIT,
    THEME_PROGRESS: TASK_TYPE_CREATIVE_PROGRESS,
    THEME_REVENUE: TASK_TYPE_DECISION_ANALYSIS,
}
DERIVED_THEME_TASK_TYPE = TASK_TYPE_MECHANISM_ITERATION


@dataclass(frozen=True)
class Project:
    """A configured project (entity). Isolation unit for everything downstream."""

    project_id: str
    name: str = ""
    domain: str = ""
    description: str = ""


@dataclass(frozen=True)
class ProjectBinding:
    """One configured input belonging to one project, with that project's slice."""

    project_id: str
    role: str = ""
    note: str = ""


@dataclass(frozen=True)
class ProjectScope:
    """What one project may see: its own resources, the shared functions, slice notes."""

    project: Project
    resources: tuple[Any, ...] = ()
    capabilities: tuple[Any, ...] = ()
    # What the model is told about resources: id + the user's one line + why this
    # project has it. The Stage 2 analysis itself goes only to the reality builder
    # and to Stage 4.
    resource_briefs: tuple[dict[str, str], ...] = ()
    # What the model is told about functions: the names, nothing else. Operation lists,
    # scopes, schemas and blurbs are left out on purpose — they would read as the
    # function's ceiling, and the model knows these tools better than our probe does.
    # {"function": 名称, "identity": 谁开发的、什么类型的工具}
    capability_briefs: tuple[dict[str, str], ...] = ()
    # function name -> capability ids, so the Host can translate what the model named
    capability_ids_by_function: dict[str, tuple[str, ...]] = field(default_factory=dict)


@dataclass(frozen=True)
class ProblemRecord:
    problem_id: str
    title: str
    problem_level: str
    root_cause: str = ""
    dimension: str = ""
    severity: int = 3
    economic_impact: str = ""
    solutions: str = ""
    reality_basis_refs: tuple[str, ...] = ()
    note: str = ""


@dataclass(frozen=True)
class ValueRecord:
    value_id: str
    title: str
    value_level: str
    value_type: str = ""
    value_score: int = 3
    economic_value: str = ""
    how_created: str = ""
    resources_used: tuple[str, ...] = ()
    capabilities_used: tuple[str, ...] = ()
    reality_basis_refs: tuple[str, ...] = ()
    note: str = ""


@dataclass(frozen=True)
class DemandRecord:
    demand_id: str
    title: str
    demand_level: str
    required_capability: str = ""
    pain_point_evidence: str = ""
    reality_basis_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class ThemePlan:
    """What to ask this project about, plus the resource context block.

    There is deliberately no function-description block: functions travel as names, and
    a written "what this function does" would both duplicate the model's own knowledge
    and read as a ceiling on it.
    """

    resource_info: str
    themes: tuple[dict[str, str], ...] = ()          # {theme, theme_kind, reason}
    skipped_fixed_themes: tuple[dict[str, str], ...] = ()   # {theme, reason}


@dataclass(frozen=True)
class ThemeCandidate:
    """A task candidate plus the lineage that makes it writable."""

    candidate: Any
    source_kind: str
    source_ref_id: str
    theme: str
    theme_kind: str


@dataclass
class ProjectChainTrace:
    """Why this project produced what it produced. Persisted next to the task files."""

    project_id: str
    reality_id: str = ""
    problems: list[ProblemRecord] = field(default_factory=list)
    values: list[ValueRecord] = field(default_factory=list)
    demands: list[DemandRecord] = field(default_factory=list)
    theme_plan: ThemePlan | None = None
    themes_asked: list[str] = field(default_factory=list)
    candidate_counts: dict[str, int] = field(default_factory=dict)
    dropped_records: dict[str, str] = field(default_factory=dict)
    dropped_candidates: dict[str, str] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)


def problem_task_type(level: str) -> tuple[str, str]:
    if str(level) == UNKNOWN_BLINDSPOT:
        return TIER_1, TASK_TYPE_UNKNOWN_PROBE
    return TIER_2, TASK_TYPE_FIX_AUDIT


def value_task_type(level: str) -> tuple[str, str]:
    if str(level) == NOVEL_PARADIGM:
        return TIER_1, TASK_TYPE_NEW_PARADIGM
    return TIER_2, TASK_TYPE_CREATIVE_PROGRESS


def demand_task_type(level: str) -> tuple[str, str]:
    if str(level) == BREAKTHROUGH_NEED:
        return TIER_1, TASK_TYPE_NEW_PARADIGM
    return TIER_2, TASK_TYPE_MECHANISM_ITERATION


def classify_task(*, theme: str, theme_kind: str, source_kind: str, source_level: str) -> dict[str, Any]:
    """Tier/type/priority are decided by the Host, never by the model.

    The theme decides it when the theme itself is a tier-1 lens (探针 / 破局); otherwise
    the source record's level decides, because an unknown blind spot or a brand-new
    scheme stays tier 1 no matter which theme surfaced it.
    """

    if theme == THEME_PROBE:
        return {"task_tier": TIER_1, "task_type": TASK_TYPE_UNKNOWN_PROBE, "priority": 5}
    if theme == THEME_PARADIGM:
        return {"task_tier": TIER_1, "task_type": TASK_TYPE_NEW_PARADIGM, "priority": 5}

    if source_kind == "problem":
        tier, task_type = problem_task_type(source_level)
    elif source_kind == "value":
        tier, task_type = value_task_type(source_level)
    else:
        tier, task_type = demand_task_type(source_level)

    if tier == TIER_2 and theme_kind == THEME_KIND_FIXED:
        task_type = THEME_TASK_TYPES.get(theme, task_type)
    elif tier == TIER_2 and theme_kind == THEME_KIND_DERIVED:
        task_type = task_type or DERIVED_THEME_TASK_TYPE

    return {
        "task_tier": tier,
        "task_type": task_type,
        "priority": 5 if tier == TIER_1 else 3,
    }


# The fixed per-theme instruction, straight from the SKILL's templates. The Host sends
# it with the theme so each theme is asked the same way every week.
THEME_INSTRUCTIONS = {
    THEME_OPTIMIZATION: "根据我提供的资源与功能信息，给我生成排查漏洞、修复冲突与止损的优化任务。",
    THEME_PROGRESS: "根据我提供的资源与功能信息，立足现有存量资产，给我生成推进下一阶段成果产出的任务。",
    THEME_REVENUE: "根据我提供的资源与功能信息，从投入产出比、机会成本对比与变现杠杆出发，给我生成提高收益的任务。",
    THEME_PROBE: "根据我提供的资源信息，假设半年后彻底失败，指出最致命的未知死穴，给我生成假设证伪探针任务。",
    THEME_PARADIGM: "根据我提供的资源与功能信息，跳出当前既有框架，给我生成突破性的全新替代方案任务。",
}


def theme_instruction(theme: str, theme_kind: str) -> str:
    fixed = THEME_INSTRUCTIONS.get(theme)
    if fixed:
        return fixed
    return (
        f"针对【{theme}主题】，根据我提供的资源与功能信息，"
        f"给我生成{theme}相关的任务。"
    )
