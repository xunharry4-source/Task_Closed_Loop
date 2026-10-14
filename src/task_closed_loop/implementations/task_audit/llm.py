from __future__ import annotations
from task_closed_loop.contracts import TaskAuditResult

class LlmTaskAuditor:
    def __init__(self, *, runtime_provider, rejection_writer=None):
        self.runtime_provider = runtime_provider
        # Implementation-level diagnostics; the locked pipeline and its artifact
        # contract are unchanged.
        self.rejection_writer = rejection_writer

    async def audit(self, batch) -> TaskAuditResult:
        components = await self.runtime_provider.validate_audit()
        generation = await components.orchestrator.task_generation.audit_drafts(
            draft=batch.draft,
            reality=batch.prepared.reality,
            existing_tasks=list(batch.existing_tasks),
            all_existing_tasks=list(batch.all_existing_tasks),
            capabilities=list(batch.prepared.capabilities),
        )
        if self.rejection_writer is not None:
            self.rejection_writer.write_rejections(generation, round_number=batch.round_number)
        return TaskAuditResult(
            generation=generation,
            tasks=tuple(generation.tasks),
            accepted_candidates=tuple(generation.accepted_candidates),
            rejected_count=len(generation.trace.rejected_candidate_contexts),
            round_number=batch.round_number,
        )
