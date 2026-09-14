from __future__ import annotations

from typing import Dict, Iterable, Iterator, List, Optional

from .base import CliEngineAdapter
from ..errors import CliEngineError


class CliEngineRouter:
    def __init__(self, adapters: Iterable[CliEngineAdapter], preferred: Optional[List[str]] = None):
        self.adapters: Dict[str, CliEngineAdapter] = {adapter.engine_id: adapter for adapter in adapters}
        self.preferred = preferred or list(self.adapters)

    def candidates(self, explicit_engine: Optional[str] = None) -> Iterator[CliEngineAdapter]:
        order = [explicit_engine] if explicit_engine else list(self.preferred)
        for engine_id in order:
            if not engine_id:
                continue
            adapter = self.adapters.get(engine_id)
            if adapter is not None:
                yield adapter

    def ready_candidates(self, explicit_engine: Optional[str] = None) -> list[CliEngineAdapter]:
        return [adapter for adapter in self.candidates(explicit_engine) if adapter.detect().ready]

    def select(self, explicit_engine: Optional[str] = None) -> CliEngineAdapter:
        ready = self.ready_candidates(explicit_engine)
        if ready:
            return ready[0]
        if explicit_engine:
            adapter = self.adapters.get(explicit_engine)
            state = adapter.detect().state if adapter else "missing"
            raise CliEngineError(f"requested CLI engine is not ready: {explicit_engine} ({state})")
        states = {engine_id: adapter.detect().state for engine_id, adapter in self.adapters.items()}
        raise CliEngineError(f"no READY CLI engine available: {states}")
