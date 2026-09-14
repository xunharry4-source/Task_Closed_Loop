from __future__ import annotations

from task_closed_loop.contracts import TaskCountDecision


class QualifiedBusinessTaskCountPolicy:
    def __init__(self, *, minimum: int):
        self.minimum = max(0, int(minimum))

    @staticmethod
    def _business(tasks):
        return tuple(
            task
            for task in tasks
            if str(task.metadata.get("origin_type", "")) != "observation_acquisition"
        )

    def evaluate(self, tasks) -> TaskCountDecision:
        qualified = self._business(tasks)
        return TaskCountDecision(
            qualified_tasks=qualified,
            threshold=self.minimum,
            too_few=len(qualified) < self.minimum,
        )
