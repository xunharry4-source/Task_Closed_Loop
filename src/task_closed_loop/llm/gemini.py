from __future__ import annotations

import asyncio
from dataclasses import asdict, is_dataclass
from datetime import datetime
import json
import os
from pathlib import Path
from typing import Any

from task_closed_loop.llm.prompt_registry import PromptRegistry
from task_closed_loop.reality.models import RealitySnapshot
from task_closed_loop.tasks.generation_models import (
    CandidateReview,
    CandidateSetReview,
    FinalTaskRealityReview,
)
from task_closed_loop.tasks.models import TaskCandidate


class GeminiConfigurationError(RuntimeError):
    pass


class GeminiDependencyError(RuntimeError):
    pass


class GeminiRequestError(RuntimeError):
    pass


class GeminiResponseError(RuntimeError):
    pass


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return {
            key: _jsonable(item)
            for key, item in asdict(value).items()
        }

    if isinstance(value, datetime):
        return value.isoformat()

    if isinstance(value, dict):
        return {
            str(key): _jsonable(item)
            for key, item in value.items()
        }

    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]

    return value


def _object_schema(
    properties: dict[str, Any],
    required: list[str],
) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


_STRING_ARRAY = {
    "type": "array",
    "items": {"type": "string"},
}


class GeminiLLM:
    """
    Google Gen AI SDK adapter using:
        client.interactions.create(...)
    """

    def __init__(
        self,
        *,
        project_root: str | Path,
        model: str,
        prompt_manifest: str = (
            "src/task_closed_loop/prompts/manifest.yml"
        ),
        roles: dict[str, str] | None = None,
        client: Any | None = None,
    ):
        model = str(model or "").strip()
        if not model:
            raise GeminiConfigurationError(
                "LLM_MODEL 未配置。"
            )

        if (
            client is None
            and not (
                os.getenv("GEMINI_API_KEY")
                or os.getenv("GOOGLE_API_KEY")
            )
        ):
            raise GeminiConfigurationError(
                "Gemini API Key 未配置。请设置 "
                "GEMINI_API_KEY 或 GOOGLE_API_KEY。"
            )

        self.model = model
        self.roles = dict(roles or {})
        self.prompts = PromptRegistry(
            project_root,
            prompt_manifest,
        )

        if client is not None:
            self.client = client
            return

        try:
            from google import genai
        except ImportError as exc:
            raise GeminiDependencyError(
                "当前 Python 环境未安装 google-genai。"
                "请运行：pip install -U google-genai"
            ) from exc

        try:
            self.client = genai.Client()
        except Exception as exc:
            raise GeminiConfigurationError(
                f"Gemini Client 初始化失败：{exc}"
            ) from exc

    def _role_prompt(
        self,
        role_key: str,
    ) -> str:
        prompt_name = self.roles.get(
            role_key,
            role_key,
        )
        return self.prompts.get(prompt_name)

    def _create_interaction(
        self,
        *,
        role_key: str,
        input_payload: dict[str, Any],
        schema: dict[str, Any],
    ):
        prompt = self._role_prompt(role_key)
        input_text = (
            prompt
            + "\n\n【本轮输入】\n"
            + json.dumps(
                _jsonable(input_payload),
                ensure_ascii=False,
                indent=2,
            )
            + "\n\n根据本轮输入完成上述职责。"
            + "输出由 response_format 约束为 JSON。"
        )

        try:
            return self.client.interactions.create(
                model=self.model,
                input=input_text,
                response_format=[
                    {
                        "type": "text",
                        "mime_type": "application/json",
                        "schema": schema,
                    }
                ],
            )
        except Exception as exc:
            raise GeminiRequestError(
                f"Gemini interactions.create 调用失败：{exc}"
            ) from exc

    async def _interaction_json(
        self,
        *,
        role_key: str,
        input_payload: dict[str, Any],
        schema: dict[str, Any],
    ) -> dict[str, Any]:
        interaction = await asyncio.to_thread(
            self._create_interaction,
            role_key=role_key,
            input_payload=input_payload,
            schema=schema,
        )

        output_text = getattr(
            interaction,
            "output_text",
            None,
        )
        if not isinstance(output_text, str):
            raise GeminiResponseError(
                "Gemini Interaction 缺少 output_text。"
            )

        try:
            parsed = json.loads(
                output_text.strip()
            )
        except json.JSONDecodeError as exc:
            raise GeminiResponseError(
                "Gemini output_text 不是可解析的 JSON。"
            ) from exc

        if not isinstance(parsed, dict):
            raise GeminiResponseError(
                "Gemini JSON 根节点必须是 object。"
            )

        return parsed

    async def build_reality(
        self,
        data,
    ) -> RealitySnapshot:
        schema = _object_schema(
            {
                "reality_id": {
                    "type": "string",
                },
                "current_facts": {
                    "type": "object",
                    "additionalProperties": True,
                },
                "current_gaps": _STRING_ARRAY,
                "current_conflicts": _STRING_ARRAY,
                "evidence_refs": _STRING_ARRAY,
                "effect_refs": _STRING_ARRAY,
                "related_history_refs": _STRING_ARRAY,
                "identity_relations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": True,
                    },
                },
            },
            [
                "reality_id",
                "current_facts",
                "current_gaps",
                "current_conflicts",
                "evidence_refs",
                "effect_refs",
                "related_history_refs",
                "identity_relations",
            ],
        )

        parsed = await self._interaction_json(
            role_key="reality_builder",
            input_payload={
                "resources": data.resources,
                "evidence": data.evidence,
                "external_effects": data.external_effects,
                "execution_deltas": data.execution_deltas,
                "related_history": data.related_history,
            },
            schema=schema,
        )

        reality_id = str(
            parsed.get("reality_id") or ""
        ).strip()
        current_facts = parsed.get(
            "current_facts"
        )

        if not reality_id:
            raise GeminiResponseError(
                "Reality Builder 缺少 reality_id。"
            )

        if not isinstance(
            current_facts,
            dict,
        ):
            raise GeminiResponseError(
                "Reality Builder current_facts "
                "必须是 object。"
            )

        return RealitySnapshot(
            reality_id=reality_id,
            current_facts=current_facts,
            current_gaps=list(
                parsed.get("current_gaps") or []
            ),
            current_conflicts=list(
                parsed.get(
                    "current_conflicts"
                )
                or []
            ),
            evidence_refs=list(
                parsed.get("evidence_refs") or []
            ),
            effect_refs=list(
                parsed.get("effect_refs") or []
            ),
            related_history_refs=list(
                parsed.get(
                    "related_history_refs"
                )
                or []
            ),
            identity_relations=list(
                parsed.get(
                    "identity_relations"
                )
                or []
            ),
        )

    async def evaluate_existing_tasks(
        self,
        reality,
        existing_tasks,
    ):
        if not existing_tasks:
            return []

        schema = _object_schema(
            {
                "effective_task_ids": _STRING_ARRAY,
                "completed_task_ids": _STRING_ARRAY,
                "invalid_task_ids": _STRING_ARRAY,
                "replaced_task_ids": _STRING_ARRAY,
            },
            [
                "effective_task_ids",
                "completed_task_ids",
                "invalid_task_ids",
                "replaced_task_ids",
            ],
        )

        parsed = await self._interaction_json(
            role_key="existing_task_continuity",
            input_payload={
                "current_reality": reality,
                "existing_tasks": existing_tasks,
            },
            schema=schema,
        )

        effective_ids = {
            str(value)
            for value in (
                parsed.get(
                    "effective_task_ids"
                )
                or []
            )
        }

        known_ids = {
            task.task_id
            for task in existing_tasks
        }
        unknown_ids = (
            effective_ids - known_ids
        )
        if unknown_ids:
            raise GeminiResponseError(
                "Task Continuity 返回未知 task_id："
                + ", ".join(
                    sorted(unknown_ids)
                )
            )

        return [
            task
            for task in existing_tasks
            if task.task_id in effective_ids
        ]

    async def discover_task_candidates(
        self,
        reality,
        existing_tasks,
        capabilities,
    ):
        candidate_schema = _object_schema(
            {
                "task_identity": {
                    "type": "string",
                },
                "reality_id": {
                    "type": "string",
                },
                "description": {
                    "type": "string",
                },
                "reality_basis": {
                    "type": "string",
                },
                "expected_reality_result": {
                    "type": "string",
                },
                "work_relation": {
                    "type": "string",
                },
                "reality_basis_refs": _STRING_ARRAY,
                "identity_anchor_refs": _STRING_ARRAY,
                "required_capability_ids": _STRING_ARRAY,
            },
            [
                "task_identity",
                "reality_id",
                "description",
                "reality_basis",
                "expected_reality_result",
                "work_relation",
                "reality_basis_refs",
                "identity_anchor_refs",
                "required_capability_ids",
            ],
        )

        schema = _object_schema(
            {
                "candidates": {
                    "type": "array",
                    "items": candidate_schema,
                }
            },
            ["candidates"],
        )

        parsed = await self._interaction_json(
            role_key="task_discovery",
            input_payload={
                "current_reality": reality,
                "effective_existing_tasks": (
                    existing_tasks
                ),
                "current_capabilities": capabilities,
            },
            schema=schema,
        )

        raw_candidates = (
            parsed.get("candidates") or []
        )
        if not isinstance(
            raw_candidates,
            list,
        ):
            raise GeminiResponseError(
                "Task Discovery candidates "
                "必须是 array。"
            )

        candidates = []
        for item in raw_candidates:
            if not isinstance(item, dict):
                raise GeminiResponseError(
                    "Candidate 必须是 object。"
                )

            candidates.append(
                TaskCandidate(
                    task_identity=str(
                        item.get(
                            "task_identity"
                        )
                        or ""
                    ),
                    reality_id=str(
                        item.get(
                            "reality_id"
                        )
                        or ""
                    ),
                    description=str(
                        item.get(
                            "description"
                        )
                        or ""
                    ),
                    reality_basis=str(
                        item.get(
                            "reality_basis"
                        )
                        or ""
                    ),
                    expected_reality_result=str(
                        item.get(
                            "expected_reality_result"
                        )
                        or ""
                    ),
                    work_relation=str(
                        item.get(
                            "work_relation"
                        )
                        or ""
                    ),
                    reality_basis_refs=tuple(
                        str(value)
                        for value in (
                            item.get(
                                "reality_basis_refs"
                            )
                            or []
                        )
                    ),
                    identity_anchor_refs=tuple(
                        str(value)
                        for value in (
                            item.get(
                                "identity_anchor_refs"
                            )
                            or []
                        )
                    ),
                    required_capability_ids=tuple(
                        str(value)
                        for value in (
                            item.get(
                                "required_capability_ids"
                            )
                            or []
                        )
                    ),
                )
            )

        return candidates

    async def destructive_review_candidate(
        self,
        reality,
        candidate,
        existing_tasks,
        capabilities,
    ):
        schema = _object_schema(
            {
                "keep": {
                    "type": "boolean",
                },
                "challenge": {
                    "type": "string",
                },
                "evidence": _STRING_ARRAY,
                "reason": {
                    "type": "string",
                },
            },
            [
                "keep",
                "challenge",
                "evidence",
                "reason",
            ],
        )

        parsed = await self._interaction_json(
            role_key="task_candidate_audit",
            input_payload={
                "current_reality": reality,
                "candidate": candidate,
                "effective_existing_tasks": (
                    existing_tasks
                ),
                "current_capabilities": capabilities,
            },
            schema=schema,
        )

        return CandidateReview(
            candidate_id=(
                candidate.candidate_id
            ),
            keep=bool(parsed["keep"]),
            challenge=str(
                parsed.get("challenge") or ""
            ),
            evidence=tuple(
                str(value)
                for value in (
                    parsed.get("evidence") or []
                )
            ),
            reason=str(
                parsed.get("reason") or ""
            ),
        )

    async def destructive_review_candidate_set(
        self,
        reality,
        candidates,
        existing_tasks,
    ):
        if not candidates:
            return CandidateSetReview(
                keep_candidate_ids=(),
                challenge="",
                reason="No candidates.",
            )

        schema = _object_schema(
            {
                "keep_candidate_ids": (
                    _STRING_ARRAY
                ),
                "challenge": {
                    "type": "string",
                },
                "evidence": _STRING_ARRAY,
                "reason": {
                    "type": "string",
                },
            },
            [
                "keep_candidate_ids",
                "challenge",
                "evidence",
                "reason",
            ],
        )

        parsed = await self._interaction_json(
            role_key="task_candidate_set_audit",
            input_payload={
                "current_reality": reality,
                "candidates": candidates,
                "effective_existing_tasks": (
                    existing_tasks
                ),
            },
            schema=schema,
        )

        keep_ids = tuple(
            str(value)
            for value in (
                parsed.get(
                    "keep_candidate_ids"
                )
                or []
            )
        )

        known_ids = {
            candidate.candidate_id
            for candidate in candidates
        }
        unknown_ids = (
            set(keep_ids) - known_ids
        )
        if unknown_ids:
            raise GeminiResponseError(
                "Candidate Set Audit 返回未知 "
                "candidate_id："
                + ", ".join(
                    sorted(unknown_ids)
                )
            )

        return CandidateSetReview(
            keep_candidate_ids=keep_ids,
            challenge=str(
                parsed.get("challenge") or ""
            ),
            evidence=tuple(
                str(value)
                for value in (
                    parsed.get("evidence") or []
                )
            ),
            reason=str(
                parsed.get("reason") or ""
            ),
        )

    async def review_final_task_reality(
        self,
        reality,
        task,
    ):
        schema = _object_schema(
            {
                "status": {
                    "type": "string",
                    "enum": [
                        "valid",
                        "completed",
                        "invalid",
                        "replaced",
                    ],
                },
                "challenge": {
                    "type": "string",
                },
                "evidence": _STRING_ARRAY,
                "reason": {
                    "type": "string",
                },
            },
            [
                "status",
                "challenge",
                "evidence",
                "reason",
            ],
        )

        parsed = await self._interaction_json(
            role_key="task_reality_validity",
            input_payload={
                "current_reality": reality,
                "task": task,
            },
            schema=schema,
        )

        status = str(
            parsed.get("status") or ""
        ).lower()

        return FinalTaskRealityReview(
            task_id=task.task_id,
            status=status,
            challenge=str(
                parsed.get("challenge") or ""
            ),
            evidence=tuple(
                str(value)
                for value in (
                    parsed.get("evidence") or []
                )
            ),
            reason=str(
                parsed.get("reason") or ""
            ),
        )
