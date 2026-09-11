from dataclasses import dataclass, field
from typing import Any

@dataclass
class InformationFlowContext:
    source_refs: list[str] = field(default_factory=list)
    derived_refs: list[str] = field(default_factory=list)
    handling_context: str | None = None
    disclosure_scope: str | None = None
    destination: dict[str, Any] | None = None
    audience: list[str] = field(default_factory=list)
    tenant_or_customer_relation: str | None = None
    transformation_relation: str | None = None
