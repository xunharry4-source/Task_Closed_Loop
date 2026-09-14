"""Compatibility exports for the frozen production pipeline.

The architecture implementation lives in ``task_closed_loop.pipeline.production``.
Do not add stage logic here.
"""
from task_closed_loop.contracts import ProductionPipelineResult, StageRecord
from task_closed_loop.pipeline.production import LockedProductionPipeline, ProductionStageError

TaskProductionPipeline = LockedProductionPipeline

__all__ = [
    "LockedProductionPipeline",
    "TaskProductionPipeline",
    "ProductionStageError",
    "ProductionPipelineResult",
    "StageRecord",
]
