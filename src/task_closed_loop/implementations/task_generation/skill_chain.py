"""Stage 3 as the SKILL's first step: project -> problem / value / demand -> task.

One instance serves exactly one project. Its resources, capabilities and reality are
that project's only; nothing from another project is ever in its input. Every candidate
it returns carries the middle-layer record it came from, and a candidate whose source
does not exist is dropped here — the rule is enforced by the Host, not by asking the
model nicely.

Feasibility is deliberately not a filter at this step (SKILL: 提任务时不考虑可行性).
A task that needs a capability the project does not have is still produced; the gap is
recorded as a demand instead. Stage 4 keeps its own judgement, unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from task_closed_loop.app.orchestrator import RuntimeCycleInput
from task_closed_loop.contracts import TaskDraftBatch
from task_closed_loop.tasks.generation_models import TaskGenerationTrace
from task_closed_loop.tasks.generator import TaskDraftBatch as DomainDraftBatch
from task_closed_loop.tasks.skill_chain_models import (
    FIXED_THEMES,
    SOURCE_KIND_TO_TABLE,
    THEME_KIND_DERIVED,
    THEME_KIND_FIXED,
    UNSKIPPABLE_THEMES,
    ProjectChainTrace,
    ProjectScope,
    classify_task,
    theme_instruction,
)


def _project_payload(scope: ProjectScope) -> dict[str, Any]:
    """What the model is told about the project: id, name, one line, and the slice notes."""

    payload: dict[str, Any] = {
        "project_id": scope.project.project_id,
        "name": scope.project.name,
    }
    if scope.project.description:
        payload["description"] = scope.project.description
    return payload


@dataclass
class ChainState:
    """What Stage 3 established for this project, reused by Stage 7.

    Stage 7 may only add tasks from the same middle-layer records: a new thinking angle
    is a new way to look at this project, not a licence to invent a new source.
    """

    reasoner: Any
    reality: Any
    problems: list[Any] = field(default_factory=list)
    values: list[Any] = field(default_factory=list)
    demands: list[Any] = field(default_factory=list)
    source_ids: dict[str, tuple[str, int]] = field(default_factory=dict)
    resource_info: str = ""
    capability_info: str = ""
    resources: list[Any] = field(default_factory=list)
    capabilities: list[Any] = field(default_factory=list)
    project_payload: dict[str, Any] = field(default_factory=dict)
    patterns: list[str] = field(default_factory=list)
    open_tasks: list[dict[str, str]] = field(default_factory=list)
    # function name -> the capability ids Stage 2 reported for it
    capability_ids_by_function: dict[str, tuple[str, ...]] = field(default_factory=dict)


def _matches_exclusion(text: str, patterns: list[str]) -> str:
    lowered = text.lower()
    for pattern in patterns:
        candidate = str(pattern or "").strip()
        if candidate and candidate.lower() in lowered:
            return candidate
    return ""


class ProjectChainTaskGenerator:
    """Stage 3 implementation for one project. Satisfies `InitialTaskGenerator`."""

    def __init__(
        self,
        *,
        runtime_provider,
        project_id: str,
        scope_provider,
        store=None,
        week: str = "",
        logger=None,
    ):
        self.runtime_provider = runtime_provider
        self.project_id = str(project_id)
        # Stage 2 runs inside the same pipeline, so the scope only exists by the time
        # generate() is called.
        self._scope_provider = scope_provider
        self.scope: ProjectScope | None = None
        self.store = store
        self.week = week
        self.logger = logger
        self.chain_trace = ProjectChainTrace(project_id=self.project_id)
        self.state: ChainState | None = None

    # -- helpers ------------------------------------------------------------

    def _log(self, message: str, *args) -> None:
        if self.logger is not None:
            self.logger.info(message, *args)

    def _exclusion_patterns(self) -> list[str]:
        """The user's 不考虑 list. Applied by the Host after generation, not as a
        prompt rule: the model is told only resources, functions and the theme."""

        if self.store is None:
            return []
        return [
            item["pattern"]
            for item in self.store.exclusions(entity_id=self.project_id)
            if item.get("pattern")
        ]

    def _open_task_context(self) -> list[dict[str, str]]:
        """Already-proposed, still-open tasks, as plain context for the model.

        Deliberately not fed into `RuntimeCycleInput.existing_tasks`: the store keeps a
        task's title/result/key, not the LLM-authored `task_identity` or anchors that
        Stage 4's duplicate rules compare, and inventing those fields would make the
        audit reject on made-up data. Cross-run de-duplication happens on the task_key
        when the task is written.
        """

        if self.store is None:
            return []
        return [
            {
                "title": task.title,
                "expected_result": task.expected_result,
                "theme": task.theme,
                "task_type": task.task_type,
                "times_proposed": str(task.times_proposed),
            }
            for task in self.store.open_tasks(entity_id=self.project_id)
        ]

    # -- the chain ----------------------------------------------------------

    async def generate(self, resources, capabilities) -> TaskDraftBatch:
        self.scope = self._scope_provider()
        components = await self.runtime_provider.validate_task()
        orchestrator = components.orchestrator
        reasoner = components.task_llm
        project = self.scope.project

        prepared = await orchestrator.prepare_context(
            RuntimeCycleInput(
                resources=list(resources),
                capabilities=list(capabilities),
                existing_tasks=[],
            )
        )
        reality = prepared.reality
        self.chain_trace.reality_id = str(reality.reality_id)
        project_payload = _project_payload(self.scope)
        trace = TaskGenerationTrace()

        if self.store is not None:
            self.store.ensure_project(
                project_id=project.project_id,
                name=project.name,
                domain=project.domain,
                description=project.description,
            )

        # Resources reach the four discovery steps and the theme calls as brief entries
        # (id + one line + slice note); their observed detail entered the chain once,
        # through the reality just built from the full resources. Stage 4 still audits
        # against the full objects.
        resource_view = [dict(brief) for brief in self.scope.resource_briefs]
        capability_view = list(self.scope.capability_briefs)
        common = {
            "project": project_payload,
            "resources": resource_view,
            "reality": reality,
            "capabilities": capability_view,
        }

        problems = await self._safe(
            "problems",
            reasoner.discover_project_problems(existing_tasks=[], **common),
            default=[],
        )
        values = await self._safe(
            "values",
            reasoner.discover_project_values(existing_tasks=[], **common),
            default=[],
        )
        # Independent of the two above: a capability gap is read off the project's own
        # resources and capabilities, not off someone else's conclusions.
        demands = await self._safe(
            "demands",
            reasoner.discover_project_demands(**common),
            default=[],
        )
        self.chain_trace.problems = list(problems)
        self.chain_trace.values = list(values)
        self.chain_trace.demands = list(demands)
        self._log(
            "stage3.chain project=%s problems=%d values=%d demands=%d",
            project.project_id,
            len(problems),
            len(values),
            len(demands),
        )

        source_ids = self._persist_middle_layers(problems, values, demands)

        plan = await self._safe(
            "theme_plan",
            reasoner.plan_project_themes(
                fixed_themes=list(FIXED_THEMES),
                previous_theme_yield=(
                    self.store.previous_theme_yield(
                        entity_id=project.project_id, week=self.week
                    )
                    if self.store is not None
                    else {}
                ),
                **common,
            ),
            default=None,
        )
        self.chain_trace.theme_plan = plan
        themes = self._themes_to_ask(plan)

        self.state = ChainState(
            reasoner=reasoner,
            reality=reality,
            problems=list(problems),
            values=list(values),
            demands=list(demands),
            source_ids=source_ids,
            resource_info=plan.resource_info if plan else "",
            capability_info=plan.capability_info if plan else "",
            resources=resource_view,
            capabilities=capability_view,
            project_payload=project_payload,
            patterns=self._exclusion_patterns(),
            open_tasks=self._open_task_context(),
            capability_ids_by_function=dict(self.scope.capability_ids_by_function or {}),
        )

        candidates: list[Any] = []
        for theme, theme_kind in themes:
            candidates.extend(await self.ask_theme(theme=theme, theme_kind=theme_kind))

        trace.rejected_discovery_reasons.update(self.chain_trace.dropped_records)
        trace.seed_validation_errors.update(self.chain_trace.dropped_candidates)
        trace.discovered_candidate_ids = [c.candidate_id for c in candidates]

        draft = DomainDraftBatch(
            discovered_candidates=candidates,
            context_resources=list(prepared.resources),
            trace=trace,
        )
        return TaskDraftBatch(
            prepared=prepared,
            draft=draft,
            existing_tasks=tuple(prepared.effective_existing_tasks),
            all_existing_tasks=tuple(prepared.all_existing_tasks),
            round_number=0,
            source_stage=3,
        )

    async def ask_theme(
        self,
        *,
        theme: str,
        theme_kind: str,
        instruction: str = "",
        extra_tasks: list[dict[str, str]] | None = None,
        stage: int = 3,
    ) -> list[Any]:
        """Ask one theme and keep only what the chain's rules allow.

        Used by Stage 3 for the fixed + derived themes, and by Stage 7 for each new
        thinking angle, so a Stage 7 task carries the same lineage as any other.
        """

        state = self.state
        if state is None:
            raise RuntimeError("Stage 3 的链条还没有建立，无法按主题生成任务。")

        theme_row_id = None
        if self.store is not None:
            theme_row_id = self.store.save_theme(
                entity_id=self.project_id,
                week=self.week,
                theme=theme,
                theme_kind=theme_kind,
                resource_info=state.resource_info,
                capability_info=state.capability_info,
            )

        produced = await self._safe(
            f"theme:{theme}",
            state.reasoner.generate_theme_tasks(
                project=state.project_payload,
                theme=theme,
                theme_kind=theme_kind,
                theme_instruction=instruction or theme_instruction(theme, theme_kind),
                resource_info=state.resource_info,
                capability_info=state.capability_info,
                resources=state.resources,
                reality=state.reality,
                capabilities=state.capabilities,
                problems=state.problems,
                values=state.values,
                demands=state.demands,
                existing_tasks=state.open_tasks + list(extra_tasks or []),
            ),
            default=[],
        )
        kept = self._accept_theme_candidates(
            produced,
            theme=theme,
            theme_kind=theme_kind,
            reality_id=str(state.reality.reality_id),
            source_ids=state.source_ids,
            problems=state.problems,
            values=state.values,
            demands=state.demands,
            patterns=state.patterns,
        )
        self.chain_trace.themes_asked.append(theme)
        self.chain_trace.candidate_counts[theme] = len(kept)
        if self.store is not None and theme_row_id is not None:
            self.store.mark_theme_asked(theme_row_id, yield_count=len(kept))
        self._log(
            "stage%d.theme project=%s theme=%s kind=%s candidates=%d",
            stage,
            self.project_id,
            theme,
            theme_kind,
            len(kept),
        )
        return kept

    async def _safe(self, step: str, awaitable, *, default):
        """A failed step records why and leaves the rest of the chain running."""

        try:
            return await awaitable
        except Exception as exc:  # noqa: BLE001 - recorded, not swallowed silently
            self.chain_trace.errors[step] = f"{type(exc).__name__}: {exc}"
            if self.logger is not None:
                self.logger.warning(
                    "stage3.chain project=%s step=%s failed: %s: %s",
                    self.project_id,
                    step,
                    type(exc).__name__,
                    exc,
                )
            return default

    def _persist_middle_layers(self, problems, values, demands) -> dict[str, tuple[str, int]]:
        """local record id -> (source_table, store id). Empty when the store is off."""

        if self.store is None:
            return {}
        entity_id = self.project_id
        source_ids: dict[str, tuple[str, int]] = {}
        for record in problems:
            row_id, _ = self.store.save_problem(entity_id=entity_id, record=record)
            source_ids[record.problem_id] = ("problems", row_id)
        for record in values:
            row_id, _ = self.store.save_value(entity_id=entity_id, record=record)
            source_ids[record.value_id] = ("value_opportunities", row_id)
        for record in demands:
            row_id, _ = self.store.save_demand(entity_id=entity_id, record=record)
            source_ids[record.demand_id] = ("capability_voids", row_id)
        return source_ids

    def _themes_to_ask(self, plan) -> list[tuple[str, str]]:
        skipped: dict[str, str] = {}
        if plan is not None:
            for item in plan.skipped_fixed_themes:
                theme = str(item.get("theme") or "").strip()
                if theme in UNSKIPPABLE_THEMES:
                    # 探针 / 破局 are never skipped, whatever the model argues.
                    self.chain_trace.dropped_records[f"skip:{theme}"] = (
                        f"模型想跳过固定主题 {theme}，但该主题不可省略，已照常提问。"
                    )
                    continue
                if theme in FIXED_THEMES:
                    skipped[theme] = str(item.get("reason") or "")

        themes = [
            (theme, THEME_KIND_FIXED) for theme in FIXED_THEMES if theme not in skipped
        ]
        for theme, reason in skipped.items():
            self.chain_trace.dropped_records[f"skip:{theme}"] = (
                f"按模型说明跳过固定主题 {theme}：{reason}"
            )

        seen = {theme for theme, _ in themes}
        if plan is not None:
            for item in plan.themes:
                theme = str(item.get("theme") or "").strip()
                if not theme or theme in seen:
                    continue
                seen.add(theme)
                themes.append((theme, THEME_KIND_DERIVED))
        return themes

    def _accept_theme_candidates(
        self,
        produced,
        *,
        theme: str,
        theme_kind: str,
        reality_id: str,
        source_ids: dict[str, tuple[str, int]],
        problems,
        values,
        demands,
        patterns: list[str],
    ) -> list[Any]:
        levels = {
            **{record.problem_id: ("problem", record.problem_level) for record in problems},
            **{record.value_id: ("value", record.value_level) for record in values},
            **{record.demand_id: ("demand", record.demand_level) for record in demands},
        }
        kept: list[Any] = []

        for candidate, source_kind, source_ref_id in produced:
            label = candidate.task_identity or candidate.candidate_id
            known = levels.get(source_ref_id)
            if not source_ref_id or known is None:
                self.chain_trace.dropped_candidates[f"{theme}:{label}"] = (
                    f"source_ref_id='{source_ref_id}' 不在本项目本轮的问题/价值/需求里，"
                    "任务必须来自真实来源记录，已丢弃。"
                )
                continue
            resolved_kind, source_level = known
            if source_kind and source_kind != resolved_kind:
                # The id is authoritative; a mislabelled kind is corrected, not fatal.
                source_kind = resolved_kind

            hit = _matches_exclusion(
                " ".join(
                    (
                        candidate.description,
                        candidate.work_relation,
                        candidate.task_identity,
                        candidate.expected_reality_result,
                    )
                ),
                patterns,
            )
            if hit:
                self.chain_trace.dropped_candidates[f"{theme}:{label}"] = (
                    f"命中排除规则 '{hit}'（用户明确不考虑），已丢弃。"
                )
                continue

            # The model named functions; map them to the capability ids the audit knows.
            needed_functions = [
                str(value).strip()
                for value in (candidate.metadata or {}).get("needed_functions") or ()
                if str(value).strip()
            ]
            capability_ids: list[str] = []
            for function_name in needed_functions:
                capability_ids.extend(
                    (self.state.capability_ids_by_function or {}).get(function_name, ())
                    if self.state is not None
                    else ()
                )

            classification = classify_task(
                theme=theme,
                theme_kind=theme_kind,
                source_kind=resolved_kind,
                source_level=source_level,
            )
            source_table = SOURCE_KIND_TO_TABLE[resolved_kind]
            store_entry = source_ids.get(source_ref_id)
            metadata = dict(candidate.metadata)
            metadata.update(
                {
                    "entity_id": self.project_id,
                    "theme": theme,
                    "theme_kind": theme_kind,
                    "source_kind": resolved_kind,
                    "source_ref_id": source_ref_id,
                    "source_table": source_table,
                    "source_level": source_level,
                    **classification,
                }
            )
            if store_entry is not None:
                metadata["source_id"] = store_entry[1]

            kept.append(
                replace(
                    candidate,
                    required_capability_ids=tuple(dict.fromkeys(capability_ids)),
                    # A clerical copy error on reality_id must not cost a good task:
                    # this project has exactly one reality and the Host knows which.
                    reality_id=reality_id,
                    metadata=metadata,
                )
            )

        return kept


MAX_THEME_CHARS = 60


def _angle_theme(angle) -> str:
    """A thinking angle becomes a derived theme name."""

    focus = " ".join(str(getattr(angle, "focus", "") or "").split())
    if not focus:
        return str(getattr(angle, "dimension_id", "") or "补充角度")
    if len(focus) > MAX_THEME_CHARS:
        focus = focus[: MAX_THEME_CHARS - 1].rstrip() + "…"
    return focus


def _angle_instruction(angle) -> str:
    question = " ".join(str(getattr(angle, "user_question", "") or "").split())
    reason = " ".join(str(getattr(angle, "value_reason", "") or "").split())
    separate = " ".join(str(getattr(angle, "independence_reason", "") or "").split())
    parts = [f"针对【{_angle_theme(angle)}】这个补充角度。"]
    if question:
        parts.append(f"要回答的问题：{question}")
    if reason:
        parts.append(f"为什么值得做：{reason}")
    if separate:
        parts.append(f"它与已有任务的区别：{separate}")
    parts.append(
        "根据我提供的资源与功能信息，在这个角度下生成任务；"
        "任务仍必须来自输入里已有的问题/价值/需求，不要新增来源。"
    )
    return " ".join(parts)


class ProjectChainTaskRegenerator:
    """Stage 7 on the same chain: each new thinking angle is asked as a derived theme.

    The alternative — the legacy discovery engine — produces candidates with no source
    record, which the task store must then refuse. Asking the angle as a theme keeps
    `问题/价值/需求 → 任务` intact for supplementary rounds too.
    """

    def __init__(self, *, generator: ProjectChainTaskGenerator, logger=None):
        self.generator = generator
        self.logger = logger
        self._asked_angle_ids: set[str] = set()

    async def regenerate(
        self,
        *,
        base_batch,
        current_tasks,
        accepted_candidates,
        dimensions,
        round_number: int,
    ) -> TaskDraftBatch:
        generator = self.generator
        chain_trace = generator.chain_trace
        before_records = dict(chain_trace.dropped_records)
        before_candidates = dict(chain_trace.dropped_candidates)

        # `dimensions` accumulates across rounds; only the new angles are asked.
        angles = []
        for angle in dimensions or ():
            angle_id = str(getattr(angle, "dimension_id", "") or "").strip() or _angle_theme(angle)
            if angle_id in self._asked_angle_ids:
                continue
            self._asked_angle_ids.add(angle_id)
            angles.append(angle)

        already_proposed = [
            {
                "title": task.description,
                "expected_result": task.expected_reality_result,
                "theme": str((task.metadata or {}).get("theme") or ""),
            }
            for task in (current_tasks or ())
        ]

        candidates: list[Any] = []
        for angle in angles:
            candidates.extend(
                await generator.ask_theme(
                    theme=_angle_theme(angle),
                    theme_kind=THEME_KIND_DERIVED,
                    instruction=_angle_instruction(angle),
                    extra_tasks=already_proposed,
                    stage=7,
                )
            )

        if self.logger is not None:
            self.logger.info(
                "stage7.chain project=%s round=%d angles=%d candidates=%d",
                generator.project_id,
                round_number,
                len(angles),
                len(candidates),
            )

        trace = TaskGenerationTrace()
        trace.coverage_expansion_attempted = True
        trace.coverage_expansion_succeeded = True
        trace.coverage_expansion_dimensions = list(dimensions or ())
        trace.rejected_discovery_reasons.update(
            {
                key: value
                for key, value in chain_trace.dropped_records.items()
                if before_records.get(key) != value
            }
        )
        trace.seed_validation_errors.update(
            {
                key: value
                for key, value in chain_trace.dropped_candidates.items()
                if before_candidates.get(key) != value
            }
        )
        trace.discovered_candidate_ids = [c.candidate_id for c in candidates]

        prepared = base_batch.prepared
        current_existing = list(prepared.effective_existing_tasks) + list(current_tasks or ())
        current_all = list(prepared.all_existing_tasks) + list(current_tasks or ())
        return TaskDraftBatch(
            prepared=prepared,
            draft=DomainDraftBatch(
                discovered_candidates=candidates,
                context_resources=list(prepared.resources),
                trace=trace,
            ),
            existing_tasks=tuple(current_existing),
            all_existing_tasks=tuple(current_all),
            round_number=round_number,
            source_stage=7,
        )
