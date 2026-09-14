from __future__ import annotations

import logging
from contextvars import ContextVar
from datetime import datetime
from typing import Any
from uuid import uuid4


LOGGER_NAME = "task_closed_loop"
_FLOW_ID: ContextVar[str] = ContextVar(
    "task_closed_loop_flow_id",
    default="-",
)


class FlowIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.flow_id = _FLOW_ID.get()
        return True


def create_flow_id() -> str:
    return "run-{}-{}".format(
        datetime.now().strftime("%Y%m%d-%H%M%S"),
        uuid4().hex[:8],
    )


def set_flow_id(flow_id: str) -> str:
    value = str(flow_id or "-")
    _FLOW_ID.set(value)
    return value


def current_flow_id() -> str:
    return _FLOW_ID.get()


def configure_runtime_logging(
    config: dict[str, Any] | None = None,
) -> logging.Logger:
    """Configure human-readable runtime diagnostics without exposing secrets."""
    logging_config = (config or {}).get("logging") or {}
    level_name = str(logging_config.get("level") or "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    if not isinstance(level, int):
        level = logging.INFO

    logging.basicConfig(
        level=level,
        format=(
            "%(asctime)s %(levelname)s %(name)s "
            "[flow_id=%(flow_id)s] "
            "[%(filename)s:%(lineno)d] %(message)s"
        ),
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    flow_filter = FlowIdFilter()
    for handler in root_logger.handlers:
        if not any(
            isinstance(item, FlowIdFilter)
            for item in handler.filters
        ):
            handler.addFilter(flow_filter)

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(level)
    return logger


def runtime_logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)


def model_label(model: Any) -> str:
    """Return provider/model metadata only; never include credentials."""
    provider = getattr(model, "provider_name", None)
    if not provider:
        provider = type(model).__name__.removesuffix("LLM")
    name = str(getattr(model, "model", "") or "")
    return f"{provider}/{name}" if name else str(provider)
