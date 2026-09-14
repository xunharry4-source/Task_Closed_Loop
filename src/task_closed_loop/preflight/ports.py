from __future__ import annotations

from typing import Any, Protocol, Sequence

from .models import PreflightCapabilityRecord, PreflightResourceRecord


class ResourceAnalyzerPort(Protocol):
    async def analyze_resources(
        self,
        raw_inputs: Sequence[Any],
    ) -> list[PreflightResourceRecord]: ...


class CapabilityAnalyzerPort(Protocol):
    async def analyze_capabilities(
        self,
        raw_inputs: Sequence[Any],
    ) -> list[PreflightCapabilityRecord]: ...
