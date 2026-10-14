from __future__ import annotations

from dataclasses import dataclass, replace
import inspect

from task_closed_loop.integration.models import (
    CapabilityDescriptor,
    ResourceSnapshot,
)
from task_closed_loop.reality.models import (
    RealitySnapshot,
)
from task_closed_loop.tasks.finalizer import (
    DeterministicTaskFinalizer,
    FinalizerFidelityAudit,
)
from task_closed_loop.tasks.generation_audit import (
    CandidateSetStructuralAudit,
    CandidateStructuralAudit,
    reference_context,
)
from task_closed_loop.tasks.generation_models import (
    CandidateFailureContext,
    DiscoverySignal,
    TaskGenerationResult,
    TaskGenerationTrace,
    TaskOutcomeRecord,
    TaskSeed,
)
from task_closed_loop.tasks.generation_ports import (
    TaskGenerationReasonerPort,
)
from task_closed_loop.tasks.models import (
    Task,
    TaskCandidate,
)
from task_closed_loop.tasks.observation import (
    build_observation_acquisition_plans,
    materialize_observation_candidate,
)
from task_closed_loop.tasks.outcomes import (
    normalize_task_outcomes,
)
from task_closed_loop.tasks.outcome_context import (
    prepare_outcomes_for_discovery,
)
from task_closed_loop.tasks.reality_validity import (
    TaskRealityValidityAudit,
)
from task_closed_loop.tasks.references import (
    TASK_OUTCOME,
    format_problems,
    reference_key,
)


@dataclass
class TaskDraftBatch:
    """Stage 3/7 output before any Stage 4 audit is allowed to run."""

    discovered_candidates: list[TaskCandidate]
    context_resources: list[ResourceSnapshot]
    trace: TaskGenerationTrace


class TaskGenerationEngine:
    def __init__(
        self,
        task_reasoner: TaskGenerationReasonerPort,
        audit_reasoner: TaskGenerationReasonerPort
        | None = None,
        candidate_audit: CandidateStructuralAudit
        | None = None,
        set_audit: CandidateSetStructuralAudit
        | None = None,
        finalizer: DeterministicTaskFinalizer
        | None = None,
        fidelity_audit: FinalizerFidelityAudit
        | None = None,
        reality_validity_audit: TaskRealityValidityAudit
        | None = None,
        coverage_expansion_min_tasks: int = 5,
        enable_need_discovery: bool = True,
        enable_task_proliferation: bool = True,
        max_inline_outcome_payload_bytes: int = 65536,
        max_total_outcome_payload_bytes: int = 262144,
    ):
        self._task_reasoner = task_reasoner
        self._audit_reasoner = (
            audit_reasoner
            if audit_reasoner is not None
            else task_reasoner
        )
        self._candidate_audit = (
            candidate_audit
            or CandidateStructuralAudit()
        )
        self._set_audit = (
            set_audit
            or CandidateSetStructuralAudit()
        )
        self._finalizer = (
            finalizer
            or DeterministicTaskFinalizer()
        )
        self._fidelity_audit = (
            fidelity_audit
            or FinalizerFidelityAudit()
        )
        self._reality_validity_audit = (
            reality_validity_audit
            or TaskRealityValidityAudit()
        )
        self._coverage_expansion_min_tasks = max(
            0,
            int(coverage_expansion_min_tasks),
        )
        self._enable_need_discovery = bool(
            enable_need_discovery
        )
        self._enable_task_proliferation = bool(
            enable_task_proliferation
        )
        self._max_inline_outcome_payload_bytes = max(1024, int(max_inline_outcome_payload_bytes))
        self._max_total_outcome_payload_bytes = max(1024, int(max_total_outcome_payload_bytes))

    async def _discover_reality_signals(
        self,
        *,
        resources: list[ResourceSnapshot],
        reality: RealitySnapshot,
        existing_tasks: list[Task],
        all_existing_tasks: list[Task],
        capabilities: list[CapabilityDescriptor],
        trace: TaskGenerationTrace,
    ) -> list[DiscoverySignal] | None:
        if not self._enable_need_discovery:
            return None

        discover = getattr(
            self._task_reasoner,
            "discover_need_opportunities",
            None,
        )
        if not callable(discover):
            # Compatibility mode for custom / test reasoners that still perform
            # direct Task Discovery. `None` means the discovery layer is absent;
            # an empty list means the layer ran and found nothing.
            return None

        try:
            raw = await discover(
                resources=resources,
                reality=reality,
                existing_tasks=existing_tasks,
                all_existing_tasks=all_existing_tasks,
                capabilities=capabilities,
            )
        except Exception as exc:
            trace.discovery_error = (
                f"{type(exc).__name__}: {exc}"
            )
            return []

        # Need/Opportunity Discovery may only stand on reality that has already
        # been observed/materialized. An observable Capability is a sensor, not a
        # business fact. Capability-only work is created by Observation Acquisition.
        references = reference_context(
            reality,
            resources,
            capabilities,
            allow_capability=False,
        )
        accepted: list[DiscoverySignal] = []
        seen: set[tuple[str, tuple[str, ...]]] = set()

        for signal in list(raw or []):
            refs = tuple(
                sorted(str(ref) for ref in signal.reality_basis_refs)
            )
            relation = " ".join(
                str(signal.reality_relation).lower().split()
            )
            missing_refs = references.problems(refs)
            reason = ""
            if not str(signal.discovery_id).strip():
                reason = "finding 缺少 finding_id。"
            elif not relation:
                reason = "finding 缺少 what_was_observed。"
            elif not str(signal.user_relevance_hypothesis).strip():
                reason = "finding 缺少 why_it_matters_to_user。"
            elif not str(signal.desired_change_or_answer).strip():
                reason = "finding 缺少 desired_outcome。"
            elif not refs:
                reason = "finding 没有给出任何 based_on_refs。"
            elif missing_refs:
                reason = (
                    "based_on_refs 中有无法在当前输入里找到的引用："
                    + format_problems(missing_refs)
                )

            key = (relation, refs)
            if not reason and key in seen:
                reason = "与本轮已接受的 Discovery Signal 是同一现实关系。"

            if reason:
                discovery_id = str(signal.discovery_id) or "<empty-discovery-id>"
                trace.rejected_discovery_ids.append(discovery_id)
                trace.rejected_discovery_reasons[discovery_id] = reason
                continue
            seen.add(key)
            accepted.append(signal)

        trace.discovery_signals.extend(accepted)
        return accepted

    @staticmethod
    def _outcome_resources(
        task_outcomes: list[TaskOutcomeRecord],
    ) -> list[ResourceSnapshot]:
        """Materialize lifecycle outcomes as evidence-bearing Resources for this cycle.

        This lets descendant materialization/audit ground child Tasks in the actual
        observation result payload instead of in the parent Capability name.
        """

        out: list[ResourceSnapshot] = []
        for outcome in task_outcomes:
            outcome_id = str(outcome.outcome_id).strip()
            if not outcome_id:
                continue
            resource_id = f"task_outcome:{outcome_id}"
            out.append(
                ResourceSnapshot(
                    resource_id=resource_id,
                    provider_id="task_runtime",
                    source_identity=resource_id,
                    resource_type="task_outcome",
                    payload={
                        "outcome_id": outcome_id,
                        "task_id": str(outcome.task_id),
                        "outcome_status": str(outcome.outcome_status),
                        "result_summary": str(outcome.result_summary),
                        "evidence_refs": list(outcome.evidence_refs),
                        "effect_refs": list(outcome.effect_refs),
                        "payload": outcome.payload,
                        "supersedes_outcome_ids": list(
                            outcome.supersedes_outcome_ids
                        ),
                        "subject_refs": list(outcome.subject_refs),
                    },
                )
            )
        return out

    def _observation_acquisition_candidates(
        self,
        *,
        reality: RealitySnapshot,
        existing_tasks: list[Task],
        all_existing_tasks: list[Task],
        task_outcomes: list[TaskOutcomeRecord],
        capabilities: list[CapabilityDescriptor],
        trace: TaskGenerationTrace,
    ) -> list[TaskCandidate]:
        trace.observation_acquisition_attempted = True
        plans, suppressed = build_observation_acquisition_plans(
            capabilities=capabilities,
            effective_existing_tasks=existing_tasks,
            all_existing_tasks=all_existing_tasks,
            task_outcomes=task_outcomes,
        )
        trace.observation_acquisition_ids.extend(
            plan.acquisition_id for plan in plans
        )
        trace.observation_acquisition_suppressed.update(suppressed)

        candidates = [
            materialize_observation_candidate(
                plan=plan,
                reality_id=reality.reality_id,
            )
            for plan in plans
        ]
        trace.observation_acquisition_candidate_ids.extend(
            candidate.candidate_id for candidate in candidates
        )
        return candidates

    @staticmethod
    def _apply_seed_provenance(
        candidate: TaskCandidate,
        seed: TaskSeed,
    ) -> TaskCandidate:
        # Provenance comes from the orchestration path, not from an LLM copying
        # fields into Candidate JSON. This keeps parent/child identity stable.
        return replace(
            candidate,
            origin_type=seed.origin_type,
            source_discovery_ids=tuple(
                seed.source_discovery_ids
            ),
            parent_task_ids=tuple(seed.parent_task_ids),
            parent_outcome_ids=tuple(
                seed.parent_outcome_ids
            ),
            proliferation_reason=(
                seed.proliferation_reason
            ),
            identity_anchor_refs=(
                tuple(seed.identity_anchor_refs)
                if tuple(seed.identity_anchor_refs)
                else tuple(candidate.identity_anchor_refs)
            ),
        )

    async def _discover_proliferation_seeds(
        self,
        *,
        resources: list[ResourceSnapshot],
        reality: RealitySnapshot,
        existing_tasks: list[Task],
        all_existing_tasks: list[Task],
        capabilities: list[CapabilityDescriptor],
        task_outcomes: list[TaskOutcomeRecord],
        trace: TaskGenerationTrace,
    ) -> list[TaskSeed]:
        if not self._enable_task_proliferation:
            return []

        discover = getattr(
            self._task_reasoner,
            "discover_task_proliferation_seeds",
            None,
        )
        if not callable(discover) or not task_outcomes:
            return []

        trace.proliferation_attempted = True

        # task_id is a lineage identity. Repeated identical historical records are
        # idempotent; conflicting records under the same task_id make any Outcome
        # that points at that ID ambiguous and therefore unusable for proliferation.
        task_by_id: dict[str, Task] = {}
        ambiguous_task_ids: set[str] = set()
        for task in all_existing_tasks:
            task_id = str(task.task_id).strip()
            if not task_id:
                continue
            previous = task_by_id.get(task_id)
            if previous is None:
                task_by_id[task_id] = task
            elif previous != task:
                ambiguous_task_ids.add(task_id)

        for task_id in ambiguous_task_ids:
            task_by_id.pop(task_id, None)

        # Outcome IDs are event identities. Identical repeats are idempotently
        # collapsed, while conflicting reuse of the same ID is rejected because
        # parent/child lineage would otherwise become ambiguous.
        outcome_by_id: dict[str, TaskOutcomeRecord] = {}
        conflicting_outcome_ids: set[str] = set()
        for outcome in task_outcomes:
            outcome_id = str(outcome.outcome_id).strip()
            task_id = str(outcome.task_id).strip()
            outcome_status = str(outcome.outcome_status).strip()
            result_summary = str(outcome.result_summary).strip()

            rejection = ""
            if not outcome_id:
                rejection = "TaskOutcomeRecord 缺少 outcome_id。"
            elif not task_id:
                rejection = "TaskOutcomeRecord 缺少 task_id。"
            elif task_id in ambiguous_task_ids:
                rejection = (
                    "TaskOutcomeRecord 引用了重复且互相冲突的 task_id；"
                    "parent lineage 无法唯一确定。"
                )
            elif task_id not in task_by_id:
                rejection = "TaskOutcomeRecord 引用了当前不存在的 parent task_id。"
            elif not outcome_status:
                rejection = "TaskOutcomeRecord 缺少 outcome_status。"
            elif not result_summary:
                rejection = "TaskOutcomeRecord 缺少 result_summary。"

            if rejection:
                if outcome_id:
                    trace.proliferation_rejected_outcomes[outcome_id] = rejection
                continue

            previous = outcome_by_id.get(outcome_id)
            if previous is None:
                outcome_by_id[outcome_id] = outcome
                continue
            if previous != outcome:
                conflicting_outcome_ids.add(outcome_id)

        for outcome_id in sorted(conflicting_outcome_ids):
            outcome_by_id.pop(outcome_id, None)
            trace.proliferation_rejected_outcomes[outcome_id] = (
                "conflicting TaskOutcomeRecord values reuse the same outcome_id"
            )

        # Long-running systems may receive a newer verified Outcome that explicitly
        # supersedes an older result from the same parent Task.  Do not let the old
        # reality remain an active proliferation trigger once that relationship is
        # declared.  Multiple outcomes are otherwise preserved: supersession is
        # explicit, never inferred from ordering or timestamps.
        superseded_outcome_ids: set[str] = set()
        for outcome in list(outcome_by_id.values()):
            supersedes = tuple(
                str(value).strip()
                for value in outcome.supersedes_outcome_ids
                if str(value).strip()
            )
            if outcome.outcome_id in supersedes:
                trace.proliferation_rejected_outcomes[outcome.outcome_id] = (
                    "TaskOutcomeRecord 不能 supersede 自己。"
                )
                outcome_by_id.pop(outcome.outcome_id, None)
                continue
            for superseded_id in supersedes:
                older = outcome_by_id.get(superseded_id)
                if older is None:
                    continue
                if str(older.task_id) != str(outcome.task_id):
                    trace.proliferation_rejected_outcomes[outcome.outcome_id] = (
                        "TaskOutcomeRecord 只能 supersede 同一 parent Task 的 Outcome。"
                    )
                    outcome_by_id.pop(outcome.outcome_id, None)
                    break
                superseded_outcome_ids.add(superseded_id)

        for superseded_id in sorted(superseded_outcome_ids):
            if superseded_id in outcome_by_id:
                outcome_by_id.pop(superseded_id, None)
                trace.proliferation_rejected_outcomes[superseded_id] = (
                    "Outcome 已被同一 parent Task 的更新 Outcome 显式 supersede。"
                )

        usable_outcomes = list(outcome_by_id.values())
        trace.proliferation_outcomes.extend(usable_outcomes)
        if not usable_outcomes:
            trace.proliferation_succeeded = True
            return []

        try:
            raw_seeds = await discover(
                resources=resources,
                reality=reality,
                existing_tasks=existing_tasks,
                all_existing_tasks=all_existing_tasks,
                capabilities=capabilities,
                task_outcomes=usable_outcomes,
            )
        except Exception as exc:
            trace.proliferation_error = (
                f"{type(exc).__name__}: {exc}"
            )
            return []

        seeds: list[TaskSeed] = []
        for seed in list(raw_seeds or []):
            seed_id = str(seed.seed_id).strip()
            parent_tasks = tuple(str(value).strip() for value in seed.parent_task_ids)
            parent_outcomes = tuple(str(value).strip() for value in seed.parent_outcome_ids)
            parent_outcome_set = set(parent_outcomes)
            referenced = [outcome_by_id.get(value) for value in parent_outcomes]
            referenced_task_ids = {
                str(outcome.task_id)
                for outcome in referenced
                if outcome is not None
            }
            expected_outcome_keys = {
                (TASK_OUTCOME, outcome_id)
                for outcome_id in parent_outcome_set
            }
            seed_basis_keys = {reference_key(value) for value in seed.reality_basis_refs}
            seed_identity_anchors = tuple(
                str(value).strip()
                for value in seed.identity_anchor_refs
                if str(value).strip()
            )
            allowed_subject_refs = {
                str(ref).strip()
                for outcome in referenced
                if outcome is not None
                for ref in tuple(outcome.subject_refs or ())
                if str(ref).strip()
            }
            # Existing materialized Resources are also safe stable anchors, cited as
            # resource:<id>. Parent task_outcome:<id> refs are deliberately not
            # considered stable object identity across re-observation cycles.
            allowed_materialized_refs = {
                f"resource:{str(resource.resource_id).strip()}"
                for resource in resources
                if str(resource.resource_id).strip()
                and not str(resource.resource_id).startswith("task_outcome:")
            }
            allowed_identity_anchors = allowed_subject_refs | allowed_materialized_refs

            error = ""
            if not seed_id:
                error = "Task proliferation seed 缺少 seed_id。"
            elif not parent_tasks or not parent_outcomes:
                error = "Task proliferation seed 必须声明 parent_task_ids 与 parent_outcome_ids。"
            elif any(not value for value in parent_tasks + parent_outcomes):
                error = "Task proliferation seed 的 parent lineage 不能包含空 ID。"
            elif len(set(parent_tasks)) != len(parent_tasks):
                error = "Task proliferation seed 的 parent_task_ids 必须去重并保持唯一。"
            elif len(parent_outcome_set) != len(parent_outcomes):
                error = "Task proliferation seed 的 parent_outcome_ids 必须去重并保持唯一。"
            elif any(outcome is None for outcome in referenced):
                error = "Task proliferation seed 引用了当前不存在或已冲突拒绝的 Outcome。"
            elif set(parent_tasks) != referenced_task_ids:
                error = (
                    "Task proliferation lineage 错配：parent_task_ids 必须与 "
                    "parent_outcome_ids 实际所属 Task 完全一致。"
                )
            elif not expected_outcome_keys.issubset(seed_basis_keys):
                error = (
                    "task idea 的 based_on_refs 必须包含每个 source_outcome_ids 对应的 "
                    "task_outcome:<outcome_id>（可带 #字段路径）；缺少："
                    + ", ".join(
                        sorted(f"{kind}:{identity}" for kind, identity in expected_outcome_keys - seed_basis_keys)
                    )
                )
            elif len(set(seed_identity_anchors)) != len(seed_identity_anchors):
                error = "task idea 的 about_object_refs 必须去重并保持唯一。"
            elif seed_identity_anchors and not set(seed_identity_anchors).issubset(allowed_identity_anchors):
                error = (
                    "task idea 的 about_object_refs 只能是来源 Outcome 的 subject_refs 原样，"
                    "或 resource:<resource_id>（不带字段路径）；禁止自行发明业务对象身份。不合规："
                    + ", ".join(sorted(set(seed_identity_anchors) - allowed_identity_anchors))
                )
            elif not str(seed.proliferation_reason).strip():
                error = "task idea 缺少 why_follow_up_is_needed。"

            if error:
                trace.seed_validation_errors[seed_id or "<empty-proliferation-seed>"] = error
                continue

            seeds.append(
                replace(
                    seed,
                    origin_type="task_proliferation",
                )
            )

        if usable_outcomes and not seeds:
            trace.proliferation_zero_seed_outcome_ids.extend(
                str(outcome.outcome_id).strip()
                for outcome in usable_outcomes
                if str(outcome.outcome_id).strip()
            )

        trace.proliferation_seeds.extend(seeds)
        trace.proliferation_succeeded = True
        return seeds

    async def _discover_candidates(
        self,
        *,
        resources: list[ResourceSnapshot],
        reality: RealitySnapshot,
        existing_tasks: list[Task],
        capabilities: list[
            CapabilityDescriptor
        ],
        trace: TaskGenerationTrace,
        thinking_dimensions=None,
        accepted_candidates=None,
        discovery_signals: list[DiscoverySignal] | None = None,
        explicit_seeds: list[TaskSeed] | None = None,
        coverage_pass: bool = False,
        proliferation_pass: bool = False,
    ) -> list[TaskCandidate]:
        seed_discovery = getattr(
            self._task_reasoner,
            "discover_task_seeds",
            None,
        )
        materialize = getattr(
            self._task_reasoner,
            "materialize_task_candidates",
            None,
        )

        if callable(materialize) and (
            explicit_seeds is not None
            or callable(seed_discovery)
        ):
            if explicit_seeds is not None:
                seeds = list(explicit_seeds)
            else:
                kwargs = {
                    "resources": resources,
                    "reality": reality,
                    "existing_tasks": existing_tasks,
                    "capabilities": capabilities,
                    "thinking_dimensions": (
                        thinking_dimensions or []
                    ),
                    "accepted_candidates": (
                        accepted_candidates or []
                    ),
                }
                parameters = inspect.signature(
                    seed_discovery
                ).parameters
                if "discovery_signals" in parameters:
                    kwargs["discovery_signals"] = (
                        discovery_signals
                    )
                seeds = list(
                    await seed_discovery(**kwargs)
                    or []
                )

                if discovery_signals is not None:
                    known_discovery_ids = {
                        str(signal.discovery_id)
                        for signal in discovery_signals
                    }
                    validated_seeds = []
                    for seed in seeds:
                        source_ids = set(
                            str(value)
                            for value in seed.source_discovery_ids
                        )
                        if (
                            not source_ids
                            or not source_ids.issubset(
                                known_discovery_ids
                            )
                        ):
                            trace.seed_validation_errors[
                                seed.seed_id
                            ] = (
                                "task idea 的 from_finding_ids 必须引用本轮 "
                                "findings 中的一个或多个 finding_id；当前可用："
                                + (", ".join(sorted(known_discovery_ids)) or "（无）")
                            )
                            continue
                        validated_seeds.append(
                            replace(
                                seed,
                                origin_type=(
                                    "reality_discovery"
                                ),
                            )
                        )
                    seeds = validated_seeds

            if coverage_pass:
                trace.coverage_expansion_seeds.extend(
                    seeds
                )
            elif not proliferation_pass:
                trace.discovery_seeds.extend(seeds)

            if not seeds:
                return []

            candidates: list[TaskCandidate] = []
            for seed in seeds:
                try:
                    materialized = await materialize(
                        resources=resources,
                        reality=reality,
                        existing_tasks=existing_tasks,
                        capabilities=capabilities,
                        seeds=[seed],
                        accepted_candidates=(
                            accepted_candidates or []
                        ),
                    )
                except Exception as exc:
                    trace.seed_materialization_errors[
                        seed.seed_id
                    ] = (
                        f"{type(exc).__name__}: {exc}"
                    )
                    continue

                candidates.extend(
                    self._apply_seed_provenance(
                        candidate,
                        seed,
                    )
                    for candidate in list(
                        materialized or []
                    )
                )
            return candidates

        # Backward-compatible path for tests / custom reasoners.
        discovery = (
            self._task_reasoner
            .discover_task_candidates
        )
        kwargs = {
            "resources": resources,
            "reality": reality,
            "existing_tasks": existing_tasks,
            "capabilities": capabilities,
        }
        parameters = inspect.signature(
            discovery
        ).parameters
        if "thinking_dimensions" in parameters:
            kwargs["thinking_dimensions"] = (
                thinking_dimensions
            )
        if "accepted_candidates" in parameters:
            kwargs["accepted_candidates"] = (
                accepted_candidates
            )
        return list(
            await discovery(**kwargs)
        )

    @staticmethod
    def _failure_context(
        *,
        candidate: TaskCandidate,
        stage: str,
        reason: str,
        field_issues=(),
        structural_findings=(),
    ) -> CandidateFailureContext:
        return CandidateFailureContext(
            candidate_id=candidate.candidate_id,
            task_identity=candidate.task_identity,
            work_relation=candidate.work_relation,
            expected_reality_result=(
                candidate.expected_reality_result
            ),
            stage=stage,
            reason=reason,
            field_issues=tuple(field_issues),
            structural_findings=tuple(
                structural_findings
            ),
        )

    async def _review_candidates(
        self,
        *,
        resources: list[ResourceSnapshot],
        reality: RealitySnapshot,
        candidates: list[TaskCandidate],
        existing_tasks: list[Task],
        all_existing_tasks: list[Task],
        capabilities: list[
            CapabilityDescriptor
        ],
        trace: TaskGenerationTrace,
    ) -> list[TaskCandidate]:
        accepted: list[TaskCandidate] = []

        for candidate in candidates:
            structural = (
                self._candidate_audit.review(
                    resources=resources,
                    reality=reality,
                    candidate=candidate,
                    existing_tasks=existing_tasks,
                    capabilities=capabilities,
                    all_existing_tasks=all_existing_tasks,
                )
            )
            trace.structural_findings.extend(
                structural
            )

            if structural:
                trace.rejected_candidate_contexts.append(
                    self._failure_context(
                        candidate=candidate,
                        stage="structural_reject",
                        reason="Structural audit failed.",
                        structural_findings=(
                            finding.message
                            for finding in structural
                        ),
                    )
                )
                continue

            # Observation Acquisition is a deterministic perception parent created
            # from the Capability contract itself. It is not a business hypothesis,
            # so an LLM value/opportunity audit must not be allowed to delete it.
            if candidate.origin_type == "observation_acquisition":
                accepted.append(candidate)
                continue

            semantic = (
                await self._audit_reasoner
                .destructive_review_candidate(
                    resources=resources,
                    reality=reality,
                    candidate=candidate,
                    existing_tasks=(
                        existing_tasks
                    ),
                    capabilities=capabilities,
                )
            )
            trace.candidate_reviews.append(
                semantic
            )

            if not semantic.core_valid:
                trace.rejected_candidate_contexts.append(
                    self._failure_context(
                        candidate=candidate,
                        stage="core_reject",
                        reason=semantic.reason,
                        field_issues=(
                            semantic.field_issues
                        ),
                    )
                )
                continue

            current = candidate

            if (
                semantic.repair_required
                or semantic.field_issues
            ):
                repair = getattr(
                    self._task_reasoner,
                    "repair_candidate_fields",
                    None,
                )

                if callable(repair):
                    try:
                        repaired_fields = await repair(
                            resources=resources,
                            reality=reality,
                            existing_tasks=existing_tasks,
                            capabilities=capabilities,
                            candidate=current,
                            field_issues=list(
                                semantic.field_issues
                            ),
                        )
                    except Exception as exc:
                        issues = list(
                            semantic.field_issues
                        )
                        issues.append(
                            "Field repair failed: "
                            f"{type(exc).__name__}: {exc}"
                        )
                        trace.unresolved_field_issues[
                            current.candidate_id
                        ] = issues
                        accepted.append(current)
                        continue

                    current = replace(
                        current,
                        description=(
                            repaired_fields.description
                        ),
                        expected_reality_result=(
                            repaired_fields
                            .expected_reality_result
                        ),
                        user_value=(
                            repaired_fields.user_value
                        ),
                        execution_steps=tuple(
                            repaired_fields
                            .execution_steps
                        ),
                    )
                    trace.repaired_candidate_ids.append(
                        current.candidate_id
                    )

                    repair_structural = (
                        self._candidate_audit.review(
                            resources=resources,
                            reality=reality,
                            candidate=current,
                            existing_tasks=existing_tasks,
                            capabilities=capabilities,
                            all_existing_tasks=all_existing_tasks,
                        )
                    )
                    trace.structural_findings.extend(
                        repair_structural
                    )

                    if repair_structural:
                        trace.rejected_candidate_contexts.append(
                            self._failure_context(
                                candidate=current,
                                stage="repair_structural_reject",
                                reason=(
                                    "Field repair violated "
                                    "structural validity."
                                ),
                                structural_findings=(
                                    finding.message
                                    for finding
                                    in repair_structural
                                ),
                            )
                        )
                        continue

                    repaired_review = (
                        await self._audit_reasoner
                        .destructive_review_candidate(
                            resources=resources,
                            reality=reality,
                            candidate=current,
                            existing_tasks=(
                                existing_tasks
                            ),
                            capabilities=capabilities,
                        )
                    )
                    trace.candidate_reviews.append(
                        repaired_review
                    )

                    if not repaired_review.core_valid:
                        trace.rejected_candidate_contexts.append(
                            self._failure_context(
                                candidate=current,
                                stage="repair_core_reject",
                                reason=(
                                    repaired_review.reason
                                ),
                                field_issues=(
                                    repaired_review
                                    .field_issues
                                ),
                            )
                        )
                        continue

                    if (
                        repaired_review.repair_required
                        or repaired_review.field_issues
                    ):
                        trace.unresolved_field_issues[
                            current.candidate_id
                        ] = list(
                            repaired_review.field_issues
                        )
                else:
                    # A field-quality problem does not invalidate
                    # an otherwise real Task relation.
                    trace.unresolved_field_issues[
                        current.candidate_id
                    ] = list(
                        semantic.field_issues
                    )

            accepted.append(current)

        return accepted

    async def _review_candidate_set(
        self,
        *,
        resources: list[ResourceSnapshot],
        reality: RealitySnapshot,
        candidates: list[TaskCandidate],
        existing_tasks: list[Task],
        capabilities: list[
            CapabilityDescriptor
        ],
        trace: TaskGenerationTrace,
    ) -> list[TaskCandidate]:
        deduped, set_structural = (
            self._set_audit.deduplicate(
                candidates
            )
        )
        trace.structural_findings.extend(
            set_structural
        )

        candidate_by_id = {
            candidate.candidate_id:
            candidate
            for candidate in candidates
        }

        for finding in set_structural:
            rejected = candidate_by_id.get(
                finding.candidate_id
            )
            if rejected is None:
                continue

            trace.rejected_candidate_contexts.append(
                self._failure_context(
                    candidate=rejected,
                    stage="set_structural_reject",
                    reason=finding.message,
                    structural_findings=(
                        finding.message,
                    ),
                )
            )

        observation_candidates = [
            candidate
            for candidate in deduped
            if candidate.origin_type == "observation_acquisition"
        ]
        business_candidates = [
            candidate
            for candidate in deduped
            if candidate.origin_type != "observation_acquisition"
        ]

        if business_candidates:
            set_review = (
                await self._audit_reasoner
                .destructive_review_candidate_set(
                    resources=resources,
                    reality=reality,
                    candidates=business_candidates,
                    existing_tasks=existing_tasks,
                    capabilities=capabilities,
                )
            )
            trace.set_review = set_review
            keep_ids = set(
                set_review.keep_candidate_ids
            )

            for candidate in business_candidates:
                if candidate.candidate_id in keep_ids:
                    continue
                trace.rejected_candidate_contexts.append(
                    self._failure_context(
                        candidate=candidate,
                        stage="set_reject",
                        reason=(
                            set_review.reason
                            or "Candidate Set Audit removed candidate."
                        ),
                    )
                )
        else:
            keep_ids = set()

        # Perception parents are not competing business alternatives and therefore
        # are not deleted by semantic Candidate Set selection.
        return observation_candidates + [
            candidate
            for candidate in business_candidates
            if candidate.candidate_id in keep_ids
        ]

    async def generate_drafts(
        self,
        reality: RealitySnapshot,
        existing_tasks: list[Task],
        capabilities: list[CapabilityDescriptor],
        resources: list[ResourceSnapshot] | None = None,
        all_existing_tasks: list[Task] | None = None,
        task_outcomes: list[TaskOutcomeRecord] | None = None,
        consumed_outcome_ids: list[str] | tuple[str, ...] | set[str] | None = None,
        thinking_dimensions=None,
        prior_accepted_candidates: list[TaskCandidate] | None = None,
    ) -> TaskDraftBatch:
        """Stage 3/7 only: discover/materialize Task candidates without auditing them.

        This exists specifically to enforce the locked production architecture where
        generation and audit are separate CLI/API calls.  The legacy ``generate``
        method remains available for non-production/runtime compatibility.
        """

        base_resources = list(resources or [])
        all_existing_tasks = list(
            all_existing_tasks if all_existing_tasks is not None else existing_tasks
        )
        task_outcomes = list(task_outcomes or [])
        trace = TaskGenerationTrace()

        normalized_outcomes = normalize_task_outcomes(task_outcomes, all_existing_tasks)
        trace.proliferation_rejected_outcomes.update(normalized_outcomes.rejected)
        prior_consumed_outcome_ids = {
            str(value).strip()
            for value in (consumed_outcome_ids or ())
            if str(value).strip()
        }
        canonical_outcomes = list(normalized_outcomes.usable)
        trace.replayed_outcome_ids.extend(
            outcome.outcome_id
            for outcome in canonical_outcomes
            if str(outcome.outcome_id).strip() in prior_consumed_outcome_ids
        )
        usable_outcomes = [
            outcome
            for outcome in canonical_outcomes
            if str(outcome.outcome_id).strip() not in prior_consumed_outcome_ids
        ]

        observation_candidates = self._observation_acquisition_candidates(
            reality=reality,
            existing_tasks=existing_tasks,
            all_existing_tasks=all_existing_tasks,
            task_outcomes=usable_outcomes,
            capabilities=capabilities,
            trace=trace,
        )
        discovery_signals = await self._discover_reality_signals(
            resources=base_resources,
            reality=reality,
            existing_tasks=existing_tasks,
            all_existing_tasks=all_existing_tasks,
            capabilities=capabilities,
            trace=trace,
        )
        discovered = list(observation_candidates)
        discovered.extend(
            await self._discover_candidates(
                resources=base_resources,
                reality=reality,
                existing_tasks=existing_tasks,
                capabilities=capabilities,
                trace=trace,
                discovery_signals=discovery_signals,
                thinking_dimensions=thinking_dimensions,
                accepted_candidates=list(prior_accepted_candidates or []),
                coverage_pass=bool(thinking_dimensions),
            )
        )

        discovery_outcomes, payload_context = prepare_outcomes_for_discovery(
            usable_outcomes,
            max_inline_bytes=self._max_inline_outcome_payload_bytes,
            max_total_bytes=self._max_total_outcome_payload_bytes,
        )
        trace.proliferation_payload_context.update(payload_context)
        outcome_resources = self._outcome_resources(discovery_outcomes)
        context_resources = base_resources + outcome_resources
        proliferation_seeds = await self._discover_proliferation_seeds(
            resources=context_resources,
            reality=reality,
            existing_tasks=existing_tasks,
            all_existing_tasks=all_existing_tasks,
            capabilities=capabilities,
            task_outcomes=discovery_outcomes,
            trace=trace,
        )
        if usable_outcomes and trace.proliferation_succeeded:
            trace.consumed_outcome_ids.extend(
                str(outcome.outcome_id).strip()
                for outcome in usable_outcomes
                if str(outcome.outcome_id).strip()
            )
        if proliferation_seeds:
            discovered.extend(
                await self._discover_candidates(
                    resources=context_resources,
                    reality=reality,
                    existing_tasks=existing_tasks,
                    capabilities=capabilities,
                    trace=trace,
                    explicit_seeds=proliferation_seeds,
                    proliferation_pass=True,
                )
            )
        trace.discovered_candidate_ids = [candidate.candidate_id for candidate in discovered]
        return TaskDraftBatch(
            discovered_candidates=discovered,
            context_resources=context_resources,
            trace=trace,
        )

    async def audit_drafts(
        self,
        *,
        draft: TaskDraftBatch,
        reality: RealitySnapshot,
        existing_tasks: list[Task],
        all_existing_tasks: list[Task],
        capabilities: list[CapabilityDescriptor],
    ) -> TaskGenerationResult:
        """Stage 4 only: audit already-generated candidates and finalize valid Tasks."""

        trace = draft.trace
        resources = list(draft.context_resources)
        discovered = list(draft.discovered_candidates)
        individually_accepted = await self._review_candidates(
            resources=resources,
            reality=reality,
            candidates=discovered,
            existing_tasks=existing_tasks,
            all_existing_tasks=all_existing_tasks,
            capabilities=capabilities,
            trace=trace,
        )
        accepted_candidates = await self._review_candidate_set(
            resources=resources,
            reality=reality,
            candidates=individually_accepted,
            existing_tasks=existing_tasks,
            capabilities=capabilities,
            trace=trace,
        )

        tasks = self._finalizer.finalize(accepted_candidates)
        trace.finalized_task_ids = [task.task_id for task in tasks]
        trace.fidelity_findings.extend(
            self._fidelity_audit.review(candidates=accepted_candidates, tasks=tasks)
        )
        trace.reality_validity_findings.extend(
            self._reality_validity_audit.review(
                resources=resources,
                reality=reality,
                capabilities=capabilities,
                tasks=tasks,
            )
        )
        structurally_invalid_task_ids: set[str] = set()
        for finding in trace.reality_validity_findings:
            if finding.startswith("task:"):
                structurally_invalid_task_ids.add(finding.split(":", 2)[1])

        semantically_valid_tasks: list[Task] = []
        for task in tasks:
            if task.task_id in structurally_invalid_task_ids:
                continue
            if str(task.metadata.get("origin_type", "")) == "observation_acquisition":
                semantically_valid_tasks.append(task)
                continue
            review = await self._audit_reasoner.review_final_task_reality(
                resources=resources,
                reality=reality,
                capabilities=capabilities,
                task=task,
            )
            trace.final_task_reality_reviews.append(review)
            if review.keeps_task:
                semantically_valid_tasks.append(task)

        return TaskGenerationResult(
            discovered_candidates=discovered,
            accepted_candidates=accepted_candidates,
            tasks=semantically_valid_tasks,
            trace=trace,
        )

    async def generate(
        self,
        reality: RealitySnapshot,
        existing_tasks: list[Task],
        capabilities: list[
            CapabilityDescriptor
        ],
        resources: list[
            ResourceSnapshot
        ] | None = None,
        all_existing_tasks: list[Task] | None = None,
        task_outcomes: list[TaskOutcomeRecord] | None = None,
        consumed_outcome_ids: list[str] | tuple[str, ...] | set[str] | None = None,
        thinking_dimensions=None,
        prior_accepted_candidates: list[TaskCandidate] | None = None,
    ) -> TaskGenerationResult:
        # `thinking_dimensions` / `prior_accepted_candidates` are how the Stage 3-7
        # production pipeline drives an explicit Stage 7 regeneration pass. They stay
        # unset for a plain single-shot generation, which keeps the engine's own
        # Coverage Expansion behaviour unchanged.
        base_resources = list(resources or [])
        all_existing_tasks = list(
            all_existing_tasks
            if all_existing_tasks is not None
            else existing_tasks
        )
        task_outcomes = list(task_outcomes or [])
        trace = TaskGenerationTrace()

        # Every Task-layer consumer must see the same canonical event set. Invalid,
        # conflicting, cyclic or superseded Outcomes must not suppress observation,
        # become task_outcome:* resources, or trigger descendants.
        normalized_outcomes = normalize_task_outcomes(
            task_outcomes,
            all_existing_tasks,
        )
        trace.proliferation_rejected_outcomes.update(
            normalized_outcomes.rejected
        )
        prior_consumed_outcome_ids = {
            str(value).strip()
            for value in (consumed_outcome_ids or ())
            if str(value).strip()
        }
        canonical_outcomes = list(normalized_outcomes.usable)
        trace.replayed_outcome_ids.extend(
            outcome.outcome_id
            for outcome in canonical_outcomes
            if str(outcome.outcome_id).strip() in prior_consumed_outcome_ids
        )
        task_outcomes = [
            outcome
            for outcome in canonical_outcomes
            if str(outcome.outcome_id).strip() not in prior_consumed_outcome_ids
        ]

        # Observation Acquisition is a separate perception layer. It is created
        # deterministically from observable Capabilities before business discovery.
        # The parent Task obtains reality; only its Outcome may trigger child Tasks.
        observation_candidates = self._observation_acquisition_candidates(
            reality=reality,
            existing_tasks=existing_tasks,
            all_existing_tasks=all_existing_tasks,
            task_outcomes=task_outcomes,
            capabilities=capabilities,
            trace=trace,
        )

        discovery_signals = await self._discover_reality_signals(
            resources=base_resources,
            reality=reality,
            existing_tasks=existing_tasks,
            all_existing_tasks=all_existing_tasks,
            capabilities=capabilities,
            trace=trace,
        )

        discovered = list(observation_candidates)
        discovered.extend(
            await self._discover_candidates(
                resources=base_resources,
                reality=reality,
                existing_tasks=existing_tasks,
                capabilities=capabilities,
                trace=trace,
                discovery_signals=discovery_signals,
                thinking_dimensions=thinking_dimensions,
                accepted_candidates=list(prior_accepted_candidates or []),
                coverage_pass=bool(thinking_dimensions),
            )
        )

        # Outcome payloads are materialized only for the downstream phase. They do
        # not retroactively allow Opportunity Discovery to guess content before an
        # observation parent has actually run. Raw execution payloads can be huge,
        # so the reasoning layer receives a bounded discovery view. Callers may
        # provide TaskOutcomeRecord.discovery_payload for a higher-quality digest.
        discovery_outcomes, payload_context = prepare_outcomes_for_discovery(
            task_outcomes,
            max_inline_bytes=self._max_inline_outcome_payload_bytes,
            max_total_bytes=self._max_total_outcome_payload_bytes,
        )
        trace.proliferation_payload_context.update(payload_context)
        outcome_resources = self._outcome_resources(discovery_outcomes)
        resources = base_resources + outcome_resources

        proliferation_seeds = (
            await self._discover_proliferation_seeds(
                resources=resources,
                reality=reality,
                existing_tasks=existing_tasks,
                all_existing_tasks=all_existing_tasks,
                capabilities=capabilities,
                task_outcomes=discovery_outcomes,
                trace=trace,
            )
        )
        if task_outcomes and trace.proliferation_succeeded:
            trace.consumed_outcome_ids.extend(
                str(outcome.outcome_id).strip()
                for outcome in task_outcomes
                if str(outcome.outcome_id).strip()
            )
        if proliferation_seeds:
            descendants = await self._discover_candidates(
                resources=resources,
                reality=reality,
                existing_tasks=existing_tasks,
                capabilities=capabilities,
                trace=trace,
                explicit_seeds=proliferation_seeds,
                proliferation_pass=True,
            )
            discovered.extend(descendants)
        trace.discovered_candidate_ids = [
            candidate.candidate_id
            for candidate in discovered
        ]

        individually_accepted = (
            await self._review_candidates(
                resources=resources,
                reality=reality,
                candidates=list(discovered),
                existing_tasks=existing_tasks,
                all_existing_tasks=all_existing_tasks,
                capabilities=capabilities,
                trace=trace,
            )
        )

        accepted_candidates = (
            await self._review_candidate_set(
                resources=resources,
                reality=reality,
                candidates=(
                    individually_accepted
                ),
                existing_tasks=existing_tasks,
                capabilities=capabilities,
                trace=trace,
            )
        )

        expansion = getattr(
            self._task_reasoner,
            "expand_thinking_dimensions",
            None,
        )

        if (
            expansion is not None
            and self._coverage_expansion_min_tasks
            > 0
            and len([
                candidate
                for candidate in accepted_candidates
                if candidate.origin_type != "observation_acquisition"
            ]) < self._coverage_expansion_min_tasks
        ):
            trace.coverage_expansion_attempted = (
                True
            )

            try:
                expansion_kwargs = {
                    "resources": resources,
                    "reality": reality,
                    "existing_tasks": existing_tasks,
                    "capabilities": capabilities,
                    "accepted_candidates": list(
                        accepted_candidates
                    ),
                }

                if (
                    "rejected_contexts"
                    in inspect.signature(
                        expansion
                    ).parameters
                ):
                    expansion_kwargs[
                        "rejected_contexts"
                    ] = list(
                        trace
                        .rejected_candidate_contexts
                    )

                dimensions = await expansion(
                    **expansion_kwargs
                )

                dimensions = list(
                    dimensions or []
                )
                trace.coverage_expansion_dimensions = (
                    dimensions
                )

                if dimensions:
                    second_pass = (
                        await self._discover_candidates(
                            resources=resources,
                            reality=reality,
                            existing_tasks=existing_tasks,
                            capabilities=capabilities,
                            trace=trace,
                            thinking_dimensions=(
                                dimensions
                            ),
                            accepted_candidates=list(
                                accepted_candidates
                            ),
                            discovery_signals=(
                                discovery_signals
                            ),
                            coverage_pass=True,
                        )
                    )

                    trace.coverage_expansion_second_pass_candidate_ids = [
                        candidate.candidate_id
                        for candidate
                        in second_pass
                    ]

                    discovered.extend(
                        second_pass
                    )
                    trace.discovered_candidate_ids = [
                        candidate.candidate_id
                        for candidate
                        in discovered
                    ]

                    second_pass_accepted = (
                        await self._review_candidates(
                            resources=resources,
                            reality=reality,
                            candidates=second_pass,
                            existing_tasks=existing_tasks,
                            all_existing_tasks=all_existing_tasks,
                            capabilities=capabilities,
                            trace=trace,
                        )
                    )

                    first_pass_ids = {
                        candidate.candidate_id
                        for candidate
                        in accepted_candidates
                    }

                    reviewed_combined = (
                        await self._review_candidate_set(
                            resources=resources,
                            reality=reality,
                            candidates=(
                                accepted_candidates
                                + second_pass_accepted
                            ),
                            existing_tasks=existing_tasks,
                            capabilities=capabilities,
                            trace=trace,
                        )
                    )

                    reviewed_by_id = {
                        candidate.candidate_id:
                        candidate
                        for candidate
                        in reviewed_combined
                    }

                    for candidate in (
                        accepted_candidates
                    ):
                        reviewed_by_id.setdefault(
                            candidate.candidate_id,
                            candidate,
                        )

                    accepted_candidates = list(
                        reviewed_by_id.values()
                    )
                    trace.coverage_expansion_preserved_first_pass_ids = [
                        candidate_id
                        for candidate_id
                        in first_pass_ids
                    ]

                trace.coverage_expansion_succeeded = (
                    True
                )

            except Exception as exc:
                trace.coverage_expansion_error = (
                    f"{type(exc).__name__}: {exc}"
                )

        tasks = self._finalizer.finalize(
            accepted_candidates
        )
        trace.finalized_task_ids = [
            task.task_id
            for task in tasks
        ]

        trace.fidelity_findings.extend(
            self._fidelity_audit.review(
                candidates=accepted_candidates,
                tasks=tasks,
            )
        )

        trace.reality_validity_findings.extend(
            self._reality_validity_audit.review(
                resources=resources,
                reality=reality,
                capabilities=capabilities,
                tasks=tasks,
            )
        )

        structurally_invalid_task_ids: set[
            str
        ] = set()

        for finding in (
            trace.reality_validity_findings
        ):
            if finding.startswith(
                "task:"
            ):
                structurally_invalid_task_ids.add(
                    finding.split(
                        ":",
                        2,
                    )[1]
                )

        semantically_valid_tasks = []

        for task in tasks:
            if (
                task.task_id
                in structurally_invalid_task_ids
            ):
                continue

            if str(task.metadata.get("origin_type", "")) == "observation_acquisition":
                semantically_valid_tasks.append(task)
                continue

            review = (
                await self._audit_reasoner
                .review_final_task_reality(
                    resources=resources,
                    reality=reality,
                    capabilities=capabilities,
                    task=task,
                )
            )
            trace.final_task_reality_reviews.append(
                review
            )

            if review.keeps_task:
                semantically_valid_tasks.append(
                    task
                )

        return TaskGenerationResult(
            discovered_candidates=discovered,
            accepted_candidates=(
                accepted_candidates
            ),
            tasks=(
                semantically_valid_tasks
            ),
            trace=trace,
        )
