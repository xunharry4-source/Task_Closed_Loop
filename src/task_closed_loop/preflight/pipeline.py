from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

from .models import PreflightAnalysisResult
from .ports import CapabilityAnalyzerPort, ResourceAnalyzerPort
from .writer import write_preflight_files


class PreflightAnalysisEngine:
    """Separate pre-task layer: understand external inputs, then emit task contracts.

    V0.37 keeps this engine outside local Task-layer tests.
    Local tests may hand-author the two standard output files. Concrete production
    analyzers/connectors can be added behind the two ports without modifying Task
    discovery, audit, proliferation, or observation-task logic.
    """

    def __init__(
        self,
        *,
        resource_analyzer: ResourceAnalyzerPort,
        capability_analyzer: CapabilityAnalyzerPort,
    ):
        self.resource_analyzer = resource_analyzer
        self.capability_analyzer = capability_analyzer

    async def run(
        self,
        *,
        raw_resources: Sequence[Any],
        raw_capabilities: Sequence[Any],
        resources_path: str | Path,
        capabilities_path: str | Path,
    ) -> PreflightAnalysisResult:
        resources = await self.resource_analyzer.analyze_resources(raw_resources)
        capabilities = await self.capability_analyzer.analyze_capabilities(raw_capabilities)
        write_preflight_files(
            resources=resources,
            capabilities=capabilities,
            resources_path=resources_path,
            capabilities_path=capabilities_path,
        )
        return PreflightAnalysisResult(
            resources=list(resources),
            capabilities=list(capabilities),
        )
