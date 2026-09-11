from task_closed_loop.integration.models import *


class MockProvider:
    def __init__(self):
        self._manifest = ProviderManifest(
            "mock",
            "mock",
            ("mock_resource",),
            ("mock_action",),
            ("mock-principal",),
            ("mock-domain",),
        )
        self._resource = ResourceSnapshot(
            "risk-1",
            "mock",
            "risk-1",
            "mock_resource",
            {
                "fact": "production certificate expires tomorrow"
            },
        )

    @property
    def manifest(self):
        return self._manifest

    async def discover_resources(self):
        return [
            ResourceDescriptor(
                "risk-1",
                "mock",
                "mock_resource",
                "risk-1",
            )
        ]

    async def read_resource(self, ref):
        return self._resource

    async def discover_capabilities(self):
        return [
            CapabilityDescriptor(
                "mock.execute",
                "mock",
                "mock_action",
                "mock-principal",
                "mock-domain",
                {"type": "mock_resource"},
                ("execute",),
            )
        ]

    async def execute(self, request):
        return ExecutionObservation(
            "mock",
            request.attempt_id,
            dict(request.target),
            {"action_type": request.action_type},
            "confirmed_committed",
            (f"receipt:{request.attempt_id}",),
            {"ok": True},
        )
