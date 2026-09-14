from __future__ import annotations

from dataclasses import dataclass, field

from task_closed_loop.reality.models import RealityBuildInput
from task_closed_loop.tasks.generation_models import (
    TaskGenerationResult,
    TaskOutcomeRecord,
)
from task_closed_loop.tasks.outcomes import (
    normalize_task_outcomes,
)


@dataclass
class RuntimeCycleInput:
    # V0.35 boundary: Task runtime receives already-analyzed Resource / Capability
    # records. It never discovers external systems or interprets raw connectors.
    resources: list = field(default_factory=list)
    capabilities: list = field(default_factory=list)
    existing_tasks: list = field(default_factory=list)
    evidence: list = field(default_factory=list)
    external_effects: list = field(default_factory=list)
    execution_deltas: list = field(default_factory=list)
    related_history: list = field(default_factory=list)
    task_outcomes: list[TaskOutcomeRecord] = field(
        default_factory=list
    )
    # Durable Outcome Receipt IDs from previous successful Task-layer cycles.
    # This prevents at-least-once event replay (including zero-child observation
    # outcomes) from suppressing new observation forever.
    consumed_outcome_ids: list[str] = field(default_factory=list)


@dataclass
class RuntimeCycleResult:
    reality: object
    effective_existing_tasks: list
    task_generation: TaskGenerationResult

    @property
    def new_tasks(self):
        return self.task_generation.tasks

    @property
    def new_task_candidates(self):
        return self.task_generation.accepted_candidates

    @property
    def discoveries(self):
        return self.task_generation.discoveries

    @property
    def observation_tasks(self):
        return self.task_generation.observation_tasks

    @property
    def consumed_outcome_ids(self):
        """Outcome Receipt IDs that the caller should persist for later cycles."""
        return list(self.task_generation.trace.consumed_outcome_ids)


@dataclass
class PreparedRuntimeContext:
    resources: list
    capabilities: list
    all_existing_tasks: list
    effective_existing_tasks: list
    task_outcomes: list[TaskOutcomeRecord]
    consumed_outcome_ids: list[str]
    reality: object


class RuntimeOrchestrator:
    def __init__(
        self,
        reality_engine,
        task_continuity,
        task_generation,
    ):
        self.reality_engine = reality_engine
        self.task_continuity = task_continuity
        self.task_generation = task_generation

    @staticmethod
    def _derive_task_outcomes(
        *,
        all_tasks,
        effective_tasks,
        external_effects,
        explicit_outcomes,
    ) -> list[TaskOutcomeRecord]:
        """Build evidence-bearing proliferation triggers without inventing outcomes.

        Explicit outcome records are authoritative. In addition, an ExternalEffect may
        close a Task relation in the newly built Reality. Only then do we synthesize a
        lifecycle outcome. Merely having a Task in the list never triggers descendants.
        """

        outcomes = list(explicit_outcomes or [])
        # Only canonical explicit Outcome IDs reserve event identity. Invalid or
        # conflicting explicit records must not squat on the deterministic
        # task-effect:<task>:<effect...> identity that a real ExternalEffect would use.

        # Only canonical explicit Outcomes are authoritative over synthesized
        # ExternalEffect outcomes. A malformed/conflicting explicit record must not
        # hide a real observed effect and create a dead cycle. Invalid records remain
        # in `outcomes` so the generation layer can report their rejection.
        normalized_explicit = normalize_task_outcomes(
            outcomes,
            all_tasks,
        )
        explicit_task_ids = {
            str(outcome.task_id).strip()
            for outcome in normalized_explicit.usable
            if str(outcome.task_id).strip()
        }
        known_outcome_ids = {
            str(outcome.outcome_id).strip()
            for outcome in normalized_explicit.usable
            if str(outcome.outcome_id).strip()
        }
        effective_ids = {
            str(task.task_id)
            for task in effective_tasks
        }

        # Historical Task IDs are lineage identities. Repeated identical records are
        # harmless, but conflicting records with the same task_id are ambiguous and
        # must never be used to synthesize an Outcome. The generation layer performs
        # the same ambiguity check for explicit Outcome records.
        all_by_id = {}
        ambiguous_task_ids: set[str] = set()
        for task in all_tasks:
            task_id = str(task.task_id).strip()
            if not task_id:
                continue
            previous = all_by_id.get(task_id)
            if previous is None:
                all_by_id[task_id] = task
            elif previous != task:
                ambiguous_task_ids.add(task_id)

        for task_id in ambiguous_task_ids:
            all_by_id.pop(task_id, None)

        effects_by_task: dict[str, list] = {}
        conflicting_effect_tasks: set[str] = set()
        effect_identity_by_task: dict[str, dict[str, object]] = {}
        for effect in external_effects:
            task_id = str(
                getattr(effect, "task_id", "") or ""
            ).strip()
            effect_id = str(
                getattr(effect, "effect_id", "") or ""
            ).strip()
            if not task_id or task_id not in all_by_id or not effect_id:
                continue

            by_id = effect_identity_by_task.setdefault(task_id, {})
            previous = by_id.get(effect_id)
            if previous is None:
                by_id[effect_id] = effect
            elif previous != effect:
                conflicting_effect_tasks.add(task_id)

        for task_id, by_id in effect_identity_by_task.items():
            if task_id in conflicting_effect_tasks:
                continue
            effects_by_task[task_id] = [
                by_id[effect_id]
                for effect_id in sorted(by_id)
            ]

        for task_id, task in all_by_id.items():
            if task_id in effective_ids:
                continue

            # Explicit TaskOutcomeRecord values are authoritative. If execution has
            # already supplied one for this Task, do not also synthesize a second
            # Outcome from the same Task's ExternalEffect records.
            if task_id in explicit_task_ids:
                continue

            effects = effects_by_task.get(task_id, [])

            # A bare lifecycle status (completed/failed/blocked/etc.) is not a
            # substantive result.  Descendant discovery requires either an explicit
            # TaskOutcomeRecord supplied by the execution layer or an actually
            # observed ExternalEffect.  This prevents an Observation parent that was
            # merely marked "completed" from inventing children before any mailbox,
            # database, drive, calendar, or other state was actually acquired.

            # An observed effect + a relation that is no longer effective is enough
            # to expose the result to descendant discovery.
            if effects:
                effect_ids = tuple(
                    str(getattr(effect, "effect_id", "") or "")
                    for effect in effects
                    if str(getattr(effect, "effect_id", "") or "")
                )
                evidence_refs = tuple(sorted({
                    str(ref)
                    for effect in effects
                    for ref in tuple(
                        getattr(effect, "evidence_refs", ()) or ()
                    )
                    if str(ref)
                }))
                subject_refs = tuple(sorted({
                    str(ref).strip()
                    for effect in effects
                    for ref in tuple(
                        getattr(effect, "subject_refs", ()) or ()
                    )
                    if str(ref).strip()
                }))
                outcome_id = (
                    "task-effect:"
                    + task_id
                    + ":"
                    + ",".join(effect_ids)
                )
                if outcome_id not in known_outcome_ids:
                    # Drop invalid/conflicting explicit records that attempted to
                    # reuse this synthetic event identity; otherwise the generation
                    # layer would see a false duplicate conflict and lose the real
                    # observed effect as well.
                    outcomes = [
                        item
                        for item in outcomes
                        if str(item.outcome_id).strip() != outcome_id
                    ]
                    commit_states = [
                        str(
                            getattr(
                                effect,
                                "commit_knowledge",
                                "",
                            )
                            or ""
                        )
                        for effect in effects
                    ]
                    outcomes.append(
                        TaskOutcomeRecord(
                            outcome_id=outcome_id,
                            task_id=task_id,
                            outcome_status=(
                                "closed_after_observed_effect"
                            ),
                            result_summary=(
                                "Task relation is no longer effective "
                                "after observed external effect(s): "
                                + ", ".join(commit_states)
                            ),
                            evidence_refs=evidence_refs,
                            effect_refs=effect_ids,
                            payload=[
                                getattr(effect, "raw_result", None)
                                for effect in effects
                            ],
                            subject_refs=subject_refs,
                        )
                    )
                    known_outcome_ids.add(outcome_id)

        return outcomes

    async def prepare_context(self, data) -> PreparedRuntimeContext:
        """Build shared reality/continuity context once before Stage 3."""

        resources = list(data.resources or [])
        capabilities = list(data.capabilities or [])
        all_existing_tasks = list(data.existing_tasks or [])
        reality = await self.reality_engine.build(
            RealityBuildInput(
                resources=resources,
                evidence=data.evidence,
                external_effects=data.external_effects,
                execution_deltas=data.execution_deltas,
                related_history=data.related_history,
            )
        )
        effective = await self.task_continuity.evaluate(reality, all_existing_tasks)
        task_outcomes = self._derive_task_outcomes(
            all_tasks=all_existing_tasks,
            effective_tasks=effective,
            external_effects=data.external_effects,
            explicit_outcomes=data.task_outcomes,
        )
        return PreparedRuntimeContext(
            resources=resources,
            capabilities=capabilities,
            all_existing_tasks=all_existing_tasks,
            effective_existing_tasks=list(effective),
            task_outcomes=list(task_outcomes),
            consumed_outcome_ids=list(data.consumed_outcome_ids or []),
            reality=reality,
        )

    async def run_cycle(
        self,
        data,
        *,
        thinking_dimensions=None,
        prior_accepted_candidates=None,
    ):
        # Compatibility single-cycle path. The locked production pipeline uses
        # prepare_context -> generate_drafts -> audit_drafts so Stage 3 and 4 are
        # physically separate calls.
        prepared = await self.prepare_context(data)
        generation = await self.task_generation.generate(
            reality=prepared.reality,
            existing_tasks=prepared.effective_existing_tasks,
            all_existing_tasks=prepared.all_existing_tasks,
            task_outcomes=prepared.task_outcomes,
            consumed_outcome_ids=prepared.consumed_outcome_ids,
            capabilities=prepared.capabilities,
            resources=prepared.resources,
            thinking_dimensions=thinking_dimensions,
            prior_accepted_candidates=list(prior_accepted_candidates or []),
        )
        return RuntimeCycleResult(
            reality=prepared.reality,
            effective_existing_tasks=prepared.effective_existing_tasks,
            task_generation=generation,
        )
