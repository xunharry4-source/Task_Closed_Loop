from __future__ import annotations

from dataclasses import replace

from task_closed_loop.integration.models import ExecutionRequest
from task_closed_loop.execution.models import Attempt, ExternalEffect


class CapabilityUnavailableError(RuntimeError):
    pass


class ExecutionRuntime:
    def __init__(self, registry):
        self._registry = registry

    async def execute(
        self,
        intent,
        context,
        capability_ref,
        action_type,
        payload,
    ):
        current_capabilities = (
            await self._registry.discover_provider_capabilities(
                capability_ref.provider_id
            )
        )

        current = next(
            (
                capability
                for capability in current_capabilities
                if capability.capability_id == capability_ref.capability_id
            ),
            None,
        )

        if current is None or str(current.availability).lower() != "available":
            raise CapabilityUnavailableError(
                f"Capability is not currently available: "
                f"{capability_ref.provider_id}/{capability_ref.capability_id}"
            )

        refreshed_context = replace(
            context,
            principal=current.principal,
            security_domain=current.security_domain,
            capabilities=tuple(
                capability.capability_id
                for capability in current_capabilities
                if str(capability.availability).lower() == "available"
            ),
        )

        attempt = Attempt.create(
            intent,
            refreshed_context.current_target,
            refreshed_context,
        )

        provider = self._registry.execution_provider(
            capability_ref.provider_id
        )

        observation = await provider.execute(
            ExecutionRequest(
                capability_ref,
                action_type,
                dict(refreshed_context.current_target),
                dict(payload),
                intent.execution_intent_id,
                attempt.attempt_id,
            )
        )

        return ExternalEffect.from_observation(
            intent.execution_intent_id,
            observation,
        )
