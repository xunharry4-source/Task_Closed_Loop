from __future__ import annotations

import re
from typing import Iterable

from task_closed_loop.integration.models import CapabilityDescriptor


_OBSERVE_HINTS = {
    "read",
    "search",
    "list",
    "get",
    "fetch",
    "query",
    "scan",
    "inspect",
    "lookup",
    "find",
    "retrieve",
    "browse",
    "discover",
    "view",
    "watch",
    "monitor",
    "receive",
    "inbox",
}


def _tokens(values: Iterable[object]) -> set[str]:
    out: set[str] = set()
    for value in values:
        text = str(value or "").lower()
        out.update(
            token
            for token in re.split(r"[^a-z0-9_]+", text)
            if token
        )
    return out


def infer_can_observe_state(
    *,
    action_type: str = "",
    description: str = "",
    permissions: Iterable[str] = (),
    target_scope: dict | None = None,
    explicit: bool | None = None,
) -> bool:
    """Infer whether a capability can actively inspect current external state.

    Explicit metadata is authoritative.  Otherwise the inference is deliberately
    conservative and uses capability semantics, never a vendor/product-name allowlist.
    """

    if explicit is not None:
        return bool(explicit)

    permission_tokens = _tokens(permissions)
    if any(
        token in _OBSERVE_HINTS
        or token.startswith("read_")
        or token.startswith("search_")
        or token.startswith("list_")
        or token.startswith("query_")
        for token in permission_tokens
    ):
        return True

    text_tokens = _tokens((action_type, description))
    has_observe_verb = bool(text_tokens & _OBSERVE_HINTS) or any(
        token.startswith((
            "read_",
            "search_",
            "list_",
            "get_",
            "fetch_",
            "query_",
            "scan_",
            "inspect_",
            "lookup_",
            "find_",
            "retrieve_",
            "browse_",
            "discover_",
            "view_",
            "watch_",
            "monitor_",
        ))
        for token in text_tokens
    )

    # A clear observation verb is enough when the capability contract itself says
    # it can read/search/list/query. We intentionally do not infer permissions from
    # a vendor/product name alone.
    if has_observe_verb:
        return True

    return False


def observable_capability_ref(
    capability: CapabilityDescriptor,
) -> str:
    return f"capability:{capability.capability_id}"


def observable_capability_refs(
    capabilities: Iterable[CapabilityDescriptor],
) -> set[str]:
    return {
        observable_capability_ref(capability)
        for capability in capabilities
        if str(capability.availability).lower() == "available"
        and capability.can_observe_state
    }
