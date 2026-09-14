from __future__ import annotations

from dataclasses import replace
from datetime import datetime
import json
from typing import Any, Iterable

from task_closed_loop.tasks.generation_models import TaskOutcomeRecord


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    return value


def _json_bytes(value: Any) -> int:
    try:
        return len(json.dumps(_jsonable(value), ensure_ascii=False, default=str).encode("utf-8"))
    except Exception:
        return len(str(value).encode("utf-8", errors="replace"))


def _sample_value(
    value: Any,
    *,
    depth: int,
    max_depth: int,
    max_list_items: int,
    max_mapping_items: int,
    max_string_chars: int,
) -> Any:
    if depth >= max_depth:
        if isinstance(value, (dict, list, tuple, set)):
            return {
                "__truncated__": True,
                "reason": "max_depth",
                "type": type(value).__name__,
            }
        return value

    if isinstance(value, str):
        if len(value) <= max_string_chars:
            return value
        return {
            "__truncated_text__": True,
            "original_chars": len(value),
            "preview": value[:max_string_chars],
        }

    if isinstance(value, dict):
        items = list(value.items())
        selected = items[:max_mapping_items]
        body = {
            str(k): _sample_value(
                v,
                depth=depth + 1,
                max_depth=max_depth,
                max_list_items=max_list_items,
                max_mapping_items=max_mapping_items,
                max_string_chars=max_string_chars,
            )
            for k, v in selected
        }
        if len(items) > len(selected):
            return {
                "__truncated_mapping__": True,
                "total_keys": len(items),
                "items": body,
            }
        return body

    if isinstance(value, (list, tuple, set)):
        seq = list(value)
        if len(seq) <= max_list_items:
            return [
                _sample_value(
                    item,
                    depth=depth + 1,
                    max_depth=max_depth,
                    max_list_items=max_list_items,
                    max_mapping_items=max_mapping_items,
                    max_string_chars=max_string_chars,
                )
                for item in seq
            ]

        head_count = max(1, max_list_items - 1)
        sampled = [
            _sample_value(
                item,
                depth=depth + 1,
                max_depth=max_depth,
                max_list_items=max_list_items,
                max_mapping_items=max_mapping_items,
                max_string_chars=max_string_chars,
            )
            for item in seq[:head_count]
        ]
        sampled.append(
            {
                "__omitted_items__": len(seq) - head_count,
                "total_items": len(seq),
            }
        )
        return sampled

    return _jsonable(value)


def bounded_discovery_payload(value: Any, max_bytes: int) -> tuple[Any, dict[str, Any]]:
    """Return a bounded, JSON-safe discovery view without mutating the raw payload.

    Small payloads pass through unchanged. Large payloads become an explicitly marked
    structural preview so LLM prompts cannot grow without bound. The preview is a
    safety fallback, not a claim that omitted content is irrelevant. Callers can
    provide TaskOutcomeRecord.discovery_payload when they have a better evidence-
    bearing digest.
    """

    budget = max(1024, int(max_bytes))
    source = _jsonable(value)
    original_bytes = _json_bytes(source)
    if original_bytes <= budget:
        return source, {
            "original_bytes": original_bytes,
            "prepared_bytes": original_bytes,
            "compacted": False,
            "source": "payload",
        }

    presets = (
        (8, 16, 48, 1800),
        (7, 10, 32, 1200),
        (6, 6, 20, 800),
        (5, 4, 12, 500),
        (4, 2, 8, 250),
        (3, 1, 4, 120),
    )
    for max_depth, max_list, max_map, max_str in presets:
        preview = {
            "__payload_compacted__": True,
            "__original_size_bytes__": original_bytes,
            "__warning__": (
                "This is a bounded discovery preview. Omitted content may still "
                "contain relevant evidence; do not infer that omitted items are absent."
            ),
            "preview": _sample_value(
                source,
                depth=0,
                max_depth=max_depth,
                max_list_items=max_list,
                max_mapping_items=max_map,
                max_string_chars=max_str,
            ),
        }
        prepared_bytes = _json_bytes(preview)
        if prepared_bytes <= budget:
            return preview, {
                "original_bytes": original_bytes,
                "prepared_bytes": prepared_bytes,
                "compacted": True,
                "source": "payload",
            }

    # Last-resort valid JSON string preview. It remains explicit about truncation.
    raw = json.dumps(source, ensure_ascii=False, default=str)
    reserve = 512
    text = raw[: max(1, budget - reserve)]
    preview = {
        "__payload_compacted__": True,
        "__original_size_bytes__": original_bytes,
        "__warning__": "Last-resort bounded JSON text preview; content is incomplete.",
        "preview_text": text,
    }
    while _json_bytes(preview) > budget and len(text) > 64:
        text = text[: int(len(text) * 0.8)]
        preview["preview_text"] = text
    return preview, {
        "original_bytes": original_bytes,
        "prepared_bytes": _json_bytes(preview),
        "compacted": True,
        "source": "payload",
    }


def prepare_outcomes_for_discovery(
    outcomes: Iterable[TaskOutcomeRecord],
    *,
    max_inline_bytes: int,
    max_total_bytes: int,
) -> tuple[list[TaskOutcomeRecord], dict[str, dict[str, Any]]]:
    values = list(outcomes)
    if not values:
        return [], {}

    per_outcome_budget = max(
        1024,
        min(int(max_inline_bytes), max(1024, int(max_total_bytes) // len(values))),
    )
    prepared: list[TaskOutcomeRecord] = []
    metrics: dict[str, dict[str, Any]] = {}

    for outcome in values:
        preferred = (
            outcome.discovery_payload
            if outcome.discovery_payload is not None
            else outcome.payload
        )
        payload, meta = bounded_discovery_payload(preferred, per_outcome_budget)
        if outcome.discovery_payload is not None:
            meta = dict(meta)
            meta["source"] = "discovery_payload"
        oid = str(outcome.outcome_id).strip()
        metrics[oid] = meta
        prepared.append(
            replace(
                outcome,
                payload=payload,
                discovery_payload=None,
            )
        )

    return prepared, metrics
