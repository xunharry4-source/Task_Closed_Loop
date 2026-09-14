from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Iterable

from task_closed_loop.integration.capability_semantics import (
    observable_capability_ref,
)
from task_closed_loop.integration.models import CapabilityDescriptor
from task_closed_loop.tasks.models import Task, TaskCandidate
from task_closed_loop.tasks.generation_models import TaskOutcomeRecord


@dataclass(frozen=True)
class ObservationAcquisitionPlan:
    """Deterministic parent-work plan for acquiring currently unmaterialized reality.

    Observation Acquisition is intentionally separate from Opportunity Discovery.
    A readable/searchable/listable/queryable capability is a sensor into reality, not
    itself evidence that a particular business problem already exists.
    """

    acquisition_id: str
    task_identity: str
    state_domain: str
    capability_ids: tuple[str, ...]
    observation_operations: tuple[str, ...]
    reality_basis_refs: tuple[str, ...]
    provider_ids: tuple[str, ...]
    target_scope: dict[str, object]


def _normalized_state_domain(capability: CapabilityDescriptor) -> str:
    explicit = str(capability.observable_state or "").strip()
    if explicit:
        return explicit

    scope = capability.target_scope or {}
    for key in (
        "state_domain",
        "type",
        "scope",
        "collection",
        "workspace",
        "account",
    ):
        value = str(scope.get(key) or "").strip()
        if value:
            return value

    description = str(capability.description or "").strip()
    if description:
        return description

    return str(capability.action_type or capability.capability_id).strip()


def _normalized_target_scope(capability: CapabilityDescriptor) -> str:
    # target_scope at the Task boundary is already a normalized Preflight product
    # (raw paths / URIs / credentials are rejected by the Task input loader).  It is
    # therefore part of the observable-surface identity and must not be ignored.
    scope = capability.target_scope or {}
    return json.dumps(
        scope,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _group_key(capability: CapabilityDescriptor) -> tuple[str, str, str, str, str]:
    # Capabilities that observe the same authenticated/bounded state surface should
    # create one acquisition parent rather than one task per low-level operation.
    # Distinct normalized scopes produced by Preflight are distinct surfaces.
    return (
        str(capability.provider_id or ""),
        str(capability.principal or ""),
        str(capability.security_domain or ""),
        _normalized_state_domain(capability).lower(),
        _normalized_target_scope(capability),
    )


def _identity_for_group(key: tuple[str, str, str, str, str]) -> tuple[str, str]:
    raw = json.dumps(key, ensure_ascii=False, separators=(",", ":"))
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]
    return (
        f"observation-acquisition:{digest}",
        f"observation:{digest}",
    )


def build_observation_acquisition_plans(
    *,
    capabilities: Iterable[CapabilityDescriptor],
    effective_existing_tasks: Iterable[Task],
    all_existing_tasks: Iterable[Task],
    task_outcomes: Iterable[TaskOutcomeRecord],
) -> tuple[list[ObservationAcquisitionPlan], dict[str, str]]:
    """Create one automatic acquisition plan for each observable state surface.

    Suppression rules are deterministic:
    - no duplicate while an equivalent acquisition Task is still effective;
    - do not immediately re-create the same acquisition in the cycle that is already
      processing its Outcome. The Outcome should first drive descendant discovery.
    """

    groups: dict[
        tuple[str, str, str, str, str],
        list[CapabilityDescriptor],
    ] = {}

    for capability in capabilities:
        if str(capability.availability).lower() != "available":
            continue
        if not capability.can_observe_state:
            continue
        groups.setdefault(_group_key(capability), []).append(capability)

    # Only an actually executable Observation Acquisition parent may suppress a
    # replacement plan. A normal business Task that happens to collide on
    # task_identity is not an observation lock, and an old observation whose
    # required Capability set is no longer available must not deadlock the surface.
    active_observation_tasks_by_identity: dict[str, list[Task]] = {}
    for task in effective_existing_tasks:
        if str(task.metadata.get("origin_type", "")) != "observation_acquisition":
            continue
        identity = str(task.task_identity).strip()
        if not identity:
            continue
        active_observation_tasks_by_identity.setdefault(identity, []).append(task)
    task_by_id = {
        str(task.task_id): task
        for task in all_existing_tasks
    }
    # At-least-once delivery may replay an older Outcome in a later cycle. The
    # primary zero-child protection is the durable Outcome Receipt passed into the
    # generation engine. Historical descendants remain a compatibility signal: if a
    # child already records parent_outcome_id, that event was demonstrably consumed
    # and must not keep the observable surface suppressed forever.
    historically_consumed_outcome_ids = {
        str(outcome_id).strip()
        for task in all_existing_tasks
        for outcome_id in tuple(task.metadata.get("parent_outcome_ids", ()) or ())
        if str(outcome_id).strip()
    }
    identities_with_current_outcome: set[str] = set()
    for outcome in task_outcomes:
        outcome_id = str(outcome.outcome_id).strip()
        if outcome_id and outcome_id in historically_consumed_outcome_ids:
            continue
        parent = task_by_id.get(str(outcome.task_id))
        if parent is None:
            continue
        if str(parent.metadata.get("origin_type", "")) != "observation_acquisition":
            continue
        identities_with_current_outcome.add(str(parent.task_identity))

    plans: list[ObservationAcquisitionPlan] = []
    suppressed: dict[str, str] = {}

    for key, group in sorted(groups.items(), key=lambda item: item[0]):
        acquisition_id, task_identity = _identity_for_group(key)
        active_matches = active_observation_tasks_by_identity.get(task_identity, [])
        current_group_capability_ids = {
            str(cap.capability_id)
            for cap in group
            if str(cap.availability).lower() == "available"
        }
        executable_active_match = False
        for task in active_matches:
            required = tuple(
                str(value).strip()
                for value in (
                    task.metadata.get("required_capability_ids")
                    or task.metadata.get("observation_capability_ids")
                    or ()
                )
                if str(value).strip()
            )
            # Legacy observation Tasks may not carry capability metadata. In that
            # case preserve conservative duplicate suppression. New Tasks always do.
            if not required or set(required).issubset(current_group_capability_ids):
                executable_active_match = True
                break

        if executable_active_match:
            suppressed[acquisition_id] = (
                "equivalent executable observation acquisition task is already effective"
            )
            continue
        if task_identity in identities_with_current_outcome:
            suppressed[acquisition_id] = "current cycle already contains an outcome from this observation surface"
            continue

        state_domain = _normalized_state_domain(group[0])
        capability_ids = tuple(
            sorted({str(cap.capability_id) for cap in group})
        )
        operations = tuple(
            sorted(
                {
                    str(operation)
                    for cap in group
                    for operation in (
                        cap.observation_operations
                        or (cap.action_type,)
                    )
                    if str(operation).strip()
                }
            )
        )
        basis_refs = tuple(
            observable_capability_ref(cap)
            for cap in sorted(group, key=lambda item: item.capability_id)
        )
        provider_ids = tuple(
            sorted({str(cap.provider_id) for cap in group})
        )
        target_scope = dict(group[0].target_scope or {})

        plans.append(
            ObservationAcquisitionPlan(
                acquisition_id=acquisition_id,
                task_identity=task_identity,
                state_domain=state_domain,
                capability_ids=capability_ids,
                observation_operations=operations,
                reality_basis_refs=basis_refs,
                provider_ids=provider_ids,
                target_scope=target_scope,
            )
        )

    return plans, suppressed


def materialize_observation_candidate(
    *,
    plan: ObservationAcquisitionPlan,
    reality_id: str,
) -> TaskCandidate:
    operations = ", ".join(plan.observation_operations) or "observe/read current state"
    capability_text = ", ".join(plan.capability_ids)
    basis_text = ", ".join(plan.reality_basis_refs)

    return TaskCandidate(
        task_identity=plan.task_identity,
        reality_id=reality_id,
        description=(
            f"Acquire the current observable state of {plan.state_domain} using "
            f"{capability_text}."
        ),
        reality_basis=(
            f"The current system has observation-capable access to {plan.state_domain} "
            f"through {basis_text}; concrete objects are intentionally not assumed "
            "before execution."
        ),
        expected_reality_result=(
            f"A materialized, evidence-backed observation result for {plan.state_domain}, "
            "including concrete object identifiers/content needed for downstream decisions, "
            "or an explicit verified result that no relevant objects were found in the "
            "observed scope."
        ),
        user_value=(
            "Acquire missing current reality before business tasks are inferred, so later "
            "child tasks are based on observed state rather than guessed senders, files, "
            "records, events, or other objects."
        ),
        execution_steps=(
            f"Invoke the available observation operations for {plan.state_domain}: {operations}.",
            "Materialize returned objects/state with concrete identifiers, content or evidence; do not invent objects that were not observed.",
            "Return an evidence-bearing Task Outcome containing the observed result so descendant Task Discovery can create zero, one, or many child tasks from what was actually found.",
        ),
        metadata={
            "observation_acquisition_id": plan.acquisition_id,
            "observation_state_domain": plan.state_domain,
            "observation_capability_ids": list(plan.capability_ids),
            "observation_operations": list(plan.observation_operations),
            "observation_provider_ids": list(plan.provider_ids),
            "observation_target_scope": dict(plan.target_scope),
        },
        work_relation=(
            f"Acquire current state from observable surface: {plan.state_domain}"
        ),
        reality_basis_refs=plan.reality_basis_refs,
        identity_anchor_refs=plan.reality_basis_refs,
        required_capability_ids=plan.capability_ids,
        origin_type="observation_acquisition",
    )
