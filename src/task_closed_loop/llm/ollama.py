from __future__ import annotations

import asyncio
from dataclasses import asdict, is_dataclass
from datetime import datetime
import json
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from task_closed_loop.llm.prompt_registry import PromptRegistry
from task_closed_loop.reality.models import RealitySnapshot
from task_closed_loop.tasks.generation_models import (
    CandidateReview,
    CandidateSetReview,
    FinalTaskRealityReview,
)
from task_closed_loop.tasks.models import TaskCandidate


class OllamaConfigurationError(RuntimeError):
    pass


class OllamaConnectionError(RuntimeError):
    pass


class OllamaResponseError(RuntimeError):
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


def _strip_json_fence(text: str) -> str:
    value = text.strip()

    if value.startswith("```"):
        lines = value.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        value = "\n".join(lines).strip()

    return value


class OllamaTransport:
    def __init__(
        self,
        base_url: str,
        timeout_seconds: float,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def _request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        body = None
        headers = {
            "Content-Type": "application/json",
        }

        if payload is not None:
            body = json.dumps(
                payload,
                ensure_ascii=False,
            ).encode("utf-8")

        request = Request(
            url,
            data=body,
            method=method,
            headers=headers,
        )

        try:
            with urlopen(
                request,
                timeout=self.timeout_seconds,
            ) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode(
                "utf-8",
                errors="replace",
            )
            raise OllamaConnectionError(
                f"Ollama HTTP {exc.code}: {detail}"
            ) from exc
        except URLError as exc:
            raise OllamaConnectionError(
                f"无法连接 Ollama：{url}；{exc.reason}"
            ) from exc

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise OllamaResponseError(
                "Ollama 返回了非 JSON HTTP 响应。"
            ) from exc

        if not isinstance(data, dict):
            raise OllamaResponseError(
                "Ollama HTTP 响应根节点必须是 JSON object。"
            )

        return data

    async def get_json(
        self,
        path: str,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._request_json,
            "GET",
            path,
            None,
        )

    async def post_json(
        self,
        path: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._request_json,
            "POST",
            path,
            payload,
        )


class OllamaLLM:
    def __init__(
        self,
        *,
        project_root: str | Path,
        model: str,
        base_url: str,
        timeout_seconds: float = 120,
        temperature: float = 0.0,
        keep_alive: str = "5m",
        think: bool = False,
        prompt_manifest: str = (
            "src/task_closed_loop/prompts/manifest.yml"
        ),
        roles: dict[str, str] | None = None,
        transport: OllamaTransport | Any | None = None,
    ):
        model = str(model or "").strip()
        if not model:
            raise OllamaConfigurationError(
                "LLM_MODEL 未配置。"
            )

        self.model = model
        self.temperature = float(temperature)
        self.keep_alive = str(keep_alive)
        self.think = bool(think)
        self.roles = dict(roles or {})
        self.prompts = PromptRegistry(
            project_root,
            prompt_manifest,
        )
        self.transport = (
            transport
            if transport is not None
            else OllamaTransport(
                base_url,
                float(timeout_seconds),
            )
        )

    async def validate_connection(self) -> None:
        tags = await self.transport.get_json(
            "/api/tags"
        )

        models = tags.get("models", [])
        names = {
            str(item.get("name") or item.get("model"))
            for item in models
            if isinstance(item, dict)
        }

        if self.model not in names:
            available = ", ".join(
                sorted(name for name in names if name)
            )
            suffix = (
                f" 当前可用模型：{available}"
                if available
                else " 当前 Ollama 没有返回已安装模型。"
            )
            raise OllamaConfigurationError(
                f"Ollama 模型未找到：{self.model}。"
                + suffix
            )

    def _role_prompt(
        self,
        role_key: str,
    ) -> str:
        prompt_name = self.roles.get(
            role_key,
            role_key,
        )
        return self.prompts.get(prompt_name)

    async def _chat_json(
        self,
        *,
        role_key: str,
        input_payload: dict[str, Any],
        contract: dict[str, Any],
    ) -> dict[str, Any]:
        system_prompt = self._role_prompt(
            role_key
        )

        user_payload = {
            "input": _jsonable(input_payload),
            "response_contract": contract,
        }

        response = await self.transport.post_json(
            "/api/chat",
            {
                "model": self.model,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            system_prompt
                            + "\n\n只返回一个 JSON object。"
                            + " 字段结构遵循用户提供的"
                            + " response_contract。"
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            user_payload,
                            ensure_ascii=False,
                            indent=2,
                        ),
                    },
                ],
                "format": "json",
                "stream": False,
                "think": self.think,
                "keep_alive": self.keep_alive,
                "options": {
                    "temperature": self.temperature,
                },
            },
        )

        message = response.get("message")
        if not isinstance(message, dict):
            raise OllamaResponseError(
                "Ollama /api/chat 缺少 message。"
            )

        content = message.get("content")
        if not isinstance(content, str):
            raise OllamaResponseError(
                "Ollama message.content 不是字符串。"
            )

        try:
            parsed = json.loads(
                _strip_json_fence(content)
            )
        except json.JSONDecodeError as exc:
            raise OllamaResponseError(
                "LLM 没有返回可解析的 JSON object。"
            ) from exc

        if not isinstance(parsed, dict):
            raise OllamaResponseError(
                "LLM JSON 根节点必须是 object。"
            )

        return parsed

    async def build_reality(
        self,
        data,
    ) -> RealitySnapshot:
        parsed = await self._chat_json(
            role_key="reality_builder",
            input_payload={
                "resources": data.resources,
                "evidence": data.evidence,
                "external_effects": data.external_effects,
                "execution_deltas": data.execution_deltas,
                "related_history": data.related_history,
            },
            contract={
                "reality_id": "string",
                "current_facts": "object",
                "current_gaps": ["string"],
                "current_conflicts": ["string"],
                "evidence_refs": ["string"],
                "effect_refs": ["string"],
                "related_history_refs": ["string"],
                "identity_relations": ["object"],
            },
        )

        reality_id = str(
            parsed.get("reality_id") or ""
        ).strip()
        current_facts = parsed.get(
            "current_facts"
        )

        if not reality_id:
            raise OllamaResponseError(
                "Reality Builder 缺少 reality_id。"
            )
        if not isinstance(current_facts, dict):
            raise OllamaResponseError(
                "Reality Builder current_facts 必须是 object。"
            )

        return RealitySnapshot(
            reality_id=reality_id,
            current_facts=current_facts,
            current_gaps=list(
                parsed.get("current_gaps") or []
            ),
            current_conflicts=list(
                parsed.get("current_conflicts") or []
            ),
            evidence_refs=list(
                parsed.get("evidence_refs") or []
            ),
            effect_refs=list(
                parsed.get("effect_refs") or []
            ),
            related_history_refs=list(
                parsed.get("related_history_refs") or []
            ),
            identity_relations=list(
                parsed.get("identity_relations") or []
            ),
        )

    async def evaluate_existing_tasks(
        self,
        reality,
        existing_tasks,
    ):
        if not existing_tasks:
            return []

        parsed = await self._chat_json(
            role_key="existing_task_continuity",
            input_payload={
                "current_reality": reality,
                "existing_tasks": existing_tasks,
            },
            contract={
                "effective_task_ids": ["string"],
                "completed_task_ids": ["string"],
                "invalid_task_ids": ["string"],
                "replaced_task_ids": ["string"],
            },
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

        known = {
            task.task_id
            for task in existing_tasks
        }
        unknown = effective_ids - known
        if unknown:
            raise OllamaResponseError(
                "Task Continuity 返回未知 task_id："
                + ", ".join(sorted(unknown))
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
        parsed = await self._chat_json(
            role_key="task_discovery",
            input_payload={
                "current_reality": reality,
                "effective_existing_tasks": (
                    existing_tasks
                ),
                "current_capabilities": capabilities,
            },
            contract={
                "candidates": [
                    {
                        "task_identity": "string",
                        "reality_id": "string",
                        "description": "string",
                        "reality_basis": "string",
                        "expected_reality_result": "string",
                        "work_relation": "string",
                        "reality_basis_refs": ["string"],
                        "identity_anchor_refs": ["string"],
                        "required_capability_ids": ["string"],
                    }
                ]
            },
        )

        raw_candidates = parsed.get(
            "candidates"
        ) or []
        if not isinstance(
            raw_candidates,
            list,
        ):
            raise OllamaResponseError(
                "Task Discovery candidates 必须是 array。"
            )

        out = []
        for item in raw_candidates:
            if not isinstance(item, dict):
                raise OllamaResponseError(
                    "Candidate 必须是 object。"
                )

            out.append(
                TaskCandidate(
                    task_identity=str(
                        item.get(
                            "task_identity",
                            "",
                        )
                    ),
                    reality_id=str(
                        item.get(
                            "reality_id",
                            "",
                        )
                    ),
                    description=str(
                        item.get(
                            "description",
                            "",
                        )
                    ),
                    reality_basis=str(
                        item.get(
                            "reality_basis",
                            "",
                        )
                    ),
                    expected_reality_result=str(
                        item.get(
                            "expected_reality_result",
                            "",
                        )
                    ),
                    work_relation=str(
                        item.get(
                            "work_relation",
                            "",
                        )
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

        return out

    async def destructive_review_candidate(
        self,
        reality,
        candidate,
        existing_tasks,
        capabilities,
    ):
        parsed = await self._chat_json(
            role_key="task_candidate_audit",
            input_payload={
                "current_reality": reality,
                "candidate": candidate,
                "effective_existing_tasks": existing_tasks,
                "current_capabilities": capabilities,
            },
            contract={
                "keep": "boolean",
                "challenge": "string",
                "evidence": ["string"],
                "reason": "string",
            },
        )

        return CandidateReview(
            candidate_id=candidate.candidate_id,
            keep=bool(parsed.get("keep")),
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

        parsed = await self._chat_json(
            role_key="task_candidate_set_audit",
            input_payload={
                "current_reality": reality,
                "candidates": candidates,
                "effective_existing_tasks": existing_tasks,
            },
            contract={
                "keep_candidate_ids": ["string"],
                "challenge": "string",
                "evidence": ["string"],
                "reason": "string",
            },
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
        known = {
            candidate.candidate_id
            for candidate in candidates
        }
        unknown = set(keep_ids) - known
        if unknown:
            raise OllamaResponseError(
                "Candidate Set Audit 返回未知 candidate_id："
                + ", ".join(sorted(unknown))
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
        parsed = await self._chat_json(
            role_key="task_reality_validity",
            input_payload={
                "current_reality": reality,
                "task": task,
            },
            contract={
                "status": (
                    "valid | completed | invalid | replaced"
                ),
                "challenge": "string",
                "evidence": ["string"],
                "reason": "string",
            },
        )

        status = str(
            parsed.get("status") or ""
        ).lower()
        allowed = {
            "valid",
            "completed",
            "invalid",
            "replaced",
        }
        if status not in allowed:
            raise OllamaResponseError(
                "Task Reality Validity 返回未知 status："
                + status
            )

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
