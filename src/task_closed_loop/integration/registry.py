from dataclasses import dataclass, field
from typing import Any
from .models import *
from .ports import *


@dataclass
class ProviderRegistry:
    _providers: dict[str, Any] = field(default_factory=dict)

    def register(self, provider: Any) -> None:
        if not isinstance(provider, ManifestPort):
            raise TypeError("provider must expose manifest")

        provider_id = provider.manifest.provider_id

        if provider_id in self._providers:
            raise ValueError(
                f"duplicate provider id: {provider_id}"
            )

        self._providers[provider_id] = provider

    def manifests(self):
        return [
            provider.manifest
            for provider in self._providers.values()
        ]

    async def discover_resources(self):
        out = []
        for provider in self._providers.values():
            if isinstance(provider, ResourceDiscoveryPort):
                out += await provider.discover_resources()
        return out

    async def read_resource(self, ref: ResourceRef):
        provider = self._providers[ref.provider_id]
        if not isinstance(provider, ResourceReadPort):
            raise TypeError("read unsupported")
        return await provider.read_resource(ref)

    async def discover_capabilities(self):
        out = []
        for provider in self._providers.values():
            if isinstance(provider, CapabilityDiscoveryPort):
                out += await provider.discover_capabilities()
        return out

    async def discover_provider_capabilities(
        self,
        provider_id: str,
    ):
        provider = self._providers[provider_id]
        if not isinstance(provider, CapabilityDiscoveryPort):
            raise TypeError(
                f"{provider_id} does not support capability discovery"
            )
        return await provider.discover_capabilities()

    def execution_provider(self, provider_id: str):
        provider = self._providers[provider_id]
        if not isinstance(provider, ActionExecutionPort):
            raise TypeError("execute unsupported")
        return provider
