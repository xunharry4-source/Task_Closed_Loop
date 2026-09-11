from .models import ExecutionContext

class ExecutionContextBuilder:
    def build(self, target, capabilities, ownership=None, approval=None, temporal_context=None):
        active=[c for c in capabilities if c.availability=='available']
        return ExecutionContext(
            principal=active[0].principal if active else None,
            security_domain=active[0].security_domain if active else None,
            capabilities=tuple(c.capability_id for c in active),
            ownership=ownership, approval=approval,
            temporal_context=temporal_context or {}, current_target=dict(target))
