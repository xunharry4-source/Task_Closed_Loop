"""资源与功能模版（Host 拥有，不要修改）。

所有分析实现都用这里的构造函数产出结果，保证两个模版的字段完全一致：

    资源：id / type / summary / availability / payload / metadata.source_input_ids
    功能：id / identity / availability / metadata.source_function_id

`summary` 是后续所有步骤唯一会读的那句话：这是什么、现在有什么、到什么程度。
功能的 `identity` 只说身份——谁开发的、什么类型的工具，不说它能做什么。
"""

from __future__ import annotations

from typing import Any

AVAILABLE = "available"
UNAVAILABLE = "unavailable"
FAILED = "failed"
AVAILABILITY = (AVAILABLE, UNAVAILABLE, FAILED)

RESOURCE_FIELDS = ("id", "type", "summary", "availability", "payload", "metadata")
CAPABILITY_FIELDS = ("id", "identity", "availability", "metadata")


def resource(
    *,
    id: str,
    type: str,
    summary: str,
    availability: str = AVAILABLE,
    payload: Any = None,
    source_input_ids: tuple[str, ...] | list[str] | None = None,
) -> dict[str, Any]:
    """一条资源。`source_input_ids` 默认就是这条资源自己的 id。"""

    if availability not in AVAILABILITY:
        raise ValueError(f"availability 必须是 {AVAILABILITY} 之一，收到 {availability!r}")
    if not str(summary).strip():
        raise ValueError(f"资源 {id} 缺少 summary：一句话说明这是什么、现在有什么、到什么程度")
    sources = list(source_input_ids or [id])
    return {
        "id": id,
        "type": type,
        "summary": str(summary).strip(),
        "availability": availability,
        "payload": payload if payload is not None else {},
        "metadata": {"source_input_ids": sources},
    }


def capability(
    *,
    id: str,
    identity: str = "",
    availability: str = AVAILABLE,
    source_function_id: str | None = None,
) -> dict[str, Any]:
    """一条功能。一个功能一条，不要按操作拆。

    `identity` 只写**身份**：谁开发的、是什么类型的工具。
    例如 "OpenAI 的编码代理命令行工具"、"Google 的邮箱服务"。

    **不要写它能做什么**——不写操作清单、不写支持的参数、不写适用场景。
    下游模型本来就认识这些工具；写了反而会被当成这个功能的能力上限。
    """

    if availability not in AVAILABILITY:
        raise ValueError(f"availability 必须是 {AVAILABILITY} 之一，收到 {availability!r}")
    return {
        "id": id,
        "identity": str(identity).strip(),
        "availability": availability,
        "metadata": {"source_function_id": source_function_id or id},
    }


def failed_resource(*, id: str, type: str, error: str) -> dict[str, Any]:
    return resource(
        id=id,
        type=type,
        summary=f"本轮未能分析：{error}",
        availability=FAILED,
        payload={},
    )


def failed_capability(*, id: str, error: str) -> dict[str, Any]:
    entry = capability(id=id, availability=FAILED)
    entry["metadata"]["error"] = error
    return entry
