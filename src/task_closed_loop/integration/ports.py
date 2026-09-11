from typing import Protocol, runtime_checkable
from .models import *

@runtime_checkable
class ManifestPort(Protocol):
    @property
    def manifest(self) -> ProviderManifest: ...

@runtime_checkable
class ResourceDiscoveryPort(Protocol):
    async def discover_resources(self) -> list[ResourceDescriptor]: ...

@runtime_checkable
class ResourceReadPort(Protocol):
    async def read_resource(self, ref: ResourceRef) -> ResourceSnapshot: ...

@runtime_checkable
class CapabilityDiscoveryPort(Protocol):
    async def discover_capabilities(self) -> list[CapabilityDescriptor]: ...

@runtime_checkable
class ActionExecutionPort(Protocol):
    async def execute(self, request: ExecutionRequest) -> ExecutionObservation: ...
