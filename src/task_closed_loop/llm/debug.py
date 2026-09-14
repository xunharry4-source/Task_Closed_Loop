from __future__ import annotations

import json
from typing import Any


class LLMDebugPrinter:
    """
    Prints the exact model identity and LLM input when DEBUG is enabled.

    It never changes the request payload.
    """

    def __init__(
        self,
        *,
        enabled: bool = False,
        scope: str | None = None,
    ):
        self.enabled = bool(enabled)
        self.scope = (
            str(scope).strip()
            if scope
            else None
        )

    def model_selected(
        self,
        *,
        adapter: str,
        model: str,
    ) -> None:
        if not self.enabled:
            return

        print()
        print("=" * 72)
        print("[DEBUG][LLM MODEL]")
        if self.scope:
            print(f"Scope: {self.scope}")
        print(f"Adapter: {adapter}")
        print(f"Model: {model}")
        print("=" * 72)
        print()

    def request(
        self,
        *,
        adapter: str,
        model: str,
        role: str,
        prompt: Any,
        response_contract: Any = None,
    ) -> None:
        if not self.enabled:
            return

        print()
        print("=" * 72)
        print("[DEBUG][LLM REQUEST]")
        if self.scope:
            print(f"Scope: {self.scope}")
        print(f"Adapter: {adapter}")
        print(f"Model: {model}")
        print(f"Role: {role}")
        print("-" * 72)
        print("Prompt / Input:")

        if isinstance(
            prompt,
            (dict, list),
        ):
            print(
                json.dumps(
                    prompt,
                    ensure_ascii=False,
                    indent=2,
                    default=str,
                )
            )
        else:
            print(str(prompt))

        if response_contract is not None:
            print("-" * 72)
            print("Response Contract:")
            print(
                json.dumps(
                    response_contract,
                    ensure_ascii=False,
                    indent=2,
                    default=str,
                )
            )

        print("=" * 72)
        print()
