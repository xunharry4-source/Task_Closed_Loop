from __future__ import annotations

import asyncio
from dataclasses import asdict, is_dataclass
from datetime import datetime
import json
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from task_closed_loop.llm.debug import LLMDebugPrinter
from task_closed_loop.model_io import (
    from_model_output_contract,
    to_model_contract,
    to_model_input,
)
from task_closed_loop.llm.prompt_registry import PromptRegistry
from task_closed_loop.llm import skill_chain_io
from task_closed_loop.llm.prompt_cache import PromptRequestCache
from task_closed_loop.reality.models import RealitySnapshot
from task_closed_loop.tasks.generation_models import (
    CandidateFailureContext,
    CandidateFieldRepair,
    CoverageDimension,
    DiscoverySignal,
    TaskOutcomeRecord,
    TaskSeed,
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
        debugger: LLMDebugPrinter | None = None,
        prompt_cache: PromptRequestCache | None = None,
    ):
        model = str(model or "").strip()
        if not model:
            raise OllamaConfigurationError(
                "model 未配置。"
            )

        self.model = model
        self.temperature = float(temperature)
        self.keep_alive = str(keep_alive)
        self.think = bool(think)
        self.roles = dict(roles or {})
        self.debugger = (
            debugger
            if debugger is not None
            else LLMDebugPrinter()
        )
        self.prompt_cache = prompt_cache
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
        # The model works with readable names; domain parsing keeps internal ones.
        input_payload = to_model_input(input_payload)
        contract = to_model_contract(contract)
        system_prompt = self._role_prompt(
            role_key
        )

        user_payload = {
            "input": _jsonable(input_payload),
            "response_contract": contract,
        }

        messages = [
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
        ]

        request_payload = {
            "model": self.model,
            "messages": messages,
            "format": "json",
            "stream": False,
            "think": self.think,
            "keep_alive": self.keep_alive,
            "options": {
                "temperature": self.temperature,
            },
        }

        if self.prompt_cache is not None:
            self.prompt_cache.record(
                provider="ollama",
                model=self.model,
                role_key=role_key,
                prompt=json.dumps(
                    {
                        "messages": messages,
                        "response_contract": contract,
                    },
                    ensure_ascii=False,
                    indent=2,
                    default=str,
                ),
                metadata={
                    "transport": "ollama_chat",
                    "endpoint": "/api/chat",
                },
            )

        self.debugger.request(
            adapter="ollama",
            model=self.model,
            role=role_key,
            prompt={
                "messages": messages,
            },
            response_contract=contract,
        )

        response = await self.transport.post_json(
            "/api/chat",
            request_payload,
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

        if self.prompt_cache is not None:
            self.prompt_cache.record_response(
                provider="ollama",
                model=self.model,
                role_key=role_key,
                response=content,
            )

        if not isinstance(parsed, dict):
            raise OllamaResponseError(
                "LLM JSON 根节点必须是 object。"
            )

        return from_model_output_contract(parsed, contract)

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

    async def discover_need_opportunities(
        self,
        resources,
        reality,
        existing_tasks,
        all_existing_tasks,
        capabilities,
    ):
        parsed = await self._chat_json(
            role_key="need_opportunity_discovery",
            input_payload={
                "current_resources": resources,
                "current_reality": reality,
                "effective_existing_tasks": existing_tasks,
                "all_existing_tasks": all_existing_tasks,
                "current_capabilities": capabilities,
            },
            contract={
                "discoveries": [
                    {
                        "discovery_id": "string",
                        "discovery_kind": "string",
                        "reality_relation": "string",
                        "user_relevance_hypothesis": "string",
                        "desired_change_or_answer": "string",
                        "independence_reason": "string",
                        "reality_basis_refs": ["string"],
                        "relevant_capability_ids": ["string"],
                    }
                ]
            },
        )
        raw = parsed.get("discoveries") or []
        if not isinstance(raw, list):
            raise OllamaResponseError(
                "Need / Opportunity Discovery discoveries 必须是 array。"
            )
        out = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            discovery_id = str(
                item.get("discovery_id") or ""
            ).strip()
            relation = str(
                item.get("reality_relation") or ""
            ).strip()
            relevance = str(
                item.get("user_relevance_hypothesis") or ""
            ).strip()
            desired = str(
                item.get("desired_change_or_answer") or ""
            ).strip()
            if not (discovery_id and relation and relevance and desired):
                continue
            out.append(
                DiscoverySignal(
                    discovery_id=discovery_id,
                    discovery_kind=str(
                        item.get("discovery_kind") or ""
                    ).strip(),
                    reality_relation=relation,
                    user_relevance_hypothesis=relevance,
                    desired_change_or_answer=desired,
                    independence_reason=str(
                        item.get("independence_reason") or ""
                    ).strip(),
                    reality_basis_refs=tuple(
                        str(v)
                        for v in (
                            item.get("reality_basis_refs") or []
                        )
                    ),
                    relevant_capability_ids=tuple(
                        str(v)
                        for v in (
                            item.get("relevant_capability_ids") or []
                        )
                    ),
                )
            )
        return out

    async def discover_task_proliferation_seeds(
        self,
        resources,
        reality,
        existing_tasks,
        all_existing_tasks,
        capabilities,
        task_outcomes,
    ):
        parsed = await self._chat_json(
            role_key="task_proliferation",
            input_payload={
                "current_resources": resources,
                "current_reality": reality,
                "effective_existing_tasks": existing_tasks,
                "all_existing_tasks": all_existing_tasks,
                "current_capabilities": capabilities,
                "task_outcomes": task_outcomes,
            },
            contract={
                "seeds": [
                    {
                        "seed_id": "string",
                        "work_relation": "string",
                        "result_goal": "string",
                        "user_value_hypothesis": "string",
                        "independence_reason": "string",
                        "reality_basis_refs": ["string"],
                        "required_capability_ids": ["string"],
                        "identity_anchor_refs": ["string"],
                        "parent_task_ids": ["string"],
                        "parent_outcome_ids": ["string"],
                        "proliferation_reason": "string",
                    }
                ]
            },
        )
        raw = parsed.get("seeds") or []
        if not isinstance(raw, list):
            raise OllamaResponseError(
                "Task Proliferation seeds 必须是 array。"
            )
        seeds = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            seed_id = str(item.get("seed_id") or "").strip()
            relation = str(item.get("work_relation") or "").strip()
            result_goal = str(item.get("result_goal") or "").strip()
            value = str(
                item.get("user_value_hypothesis") or ""
            ).strip()
            if not (seed_id and relation and result_goal and value):
                continue
            seeds.append(
                TaskSeed(
                    seed_id=seed_id,
                    work_relation=relation,
                    result_goal=result_goal,
                    user_value_hypothesis=value,
                    independence_reason=str(
                        item.get("independence_reason") or ""
                    ).strip(),
                    reality_basis_refs=tuple(
                        str(v)
                        for v in (item.get("reality_basis_refs") or [])
                    ),
                    required_capability_ids=tuple(
                        str(v)
                        for v in (item.get("required_capability_ids") or [])
                    ),
                    identity_anchor_refs=tuple(
                        str(v)
                        for v in (item.get("identity_anchor_refs") or [])
                    ),
                    origin_type="task_proliferation",
                    parent_task_ids=tuple(
                        str(v)
                        for v in (item.get("parent_task_ids") or [])
                    ),
                    parent_outcome_ids=tuple(
                        str(v)
                        for v in (item.get("parent_outcome_ids") or [])
                    ),
                    proliferation_reason=str(
                        item.get("proliferation_reason") or ""
                    ).strip(),
                )
            )
        return seeds

    async def discover_task_seeds(
        self,
        resources,
        reality,
        existing_tasks,
        capabilities,
        thinking_dimensions=None,
        accepted_candidates=None,
        discovery_signals=None,
    ):
        parsed = await self._chat_json(
            role_key="task_discovery",
            input_payload={
                "discovery_phase": "breadth",
                "current_resources": resources,
                "current_reality": reality,
                "effective_existing_tasks": existing_tasks,
                "current_capabilities": capabilities,
                "coverage_thinking_dimensions": (
                    thinking_dimensions or []
                ),
                "first_pass_accepted_candidates": (
                    accepted_candidates or []
                ),
                "discovery_signals": discovery_signals,
            },
            contract={
                "seeds": [
                    {
                        "seed_id": "string",
                        "work_relation": "string",
                        "result_goal": "string",
                        "user_value_hypothesis": "string",
                        "independence_reason": "string",
                        "reality_basis_refs": ["string"],
                        "required_capability_ids": ["string"],
                        "source_discovery_ids": ["string"],
                    }
                ]
            },
        )
        raw = parsed.get("seeds") or []
        if not isinstance(raw, list):
            raise OllamaResponseError(
                "Task Discovery seeds 必须是 array。"
            )
        seeds = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            seed_id = str(item.get("seed_id") or "").strip()
            relation = str(item.get("work_relation") or "").strip()
            result_goal = str(item.get("result_goal") or "").strip()
            value = str(item.get("user_value_hypothesis") or "").strip()
            if not (seed_id and relation and result_goal and value):
                continue
            seeds.append(
                TaskSeed(
                    seed_id=seed_id,
                    work_relation=relation,
                    result_goal=result_goal,
                    user_value_hypothesis=value,
                    independence_reason=str(
                        item.get("independence_reason") or ""
                    ).strip(),
                    reality_basis_refs=tuple(
                        str(v)
                        for v in (item.get("reality_basis_refs") or [])
                    ),
                    required_capability_ids=tuple(
                        str(v)
                        for v in (item.get("required_capability_ids") or [])
                    ),
                    origin_type="reality_discovery",
                    source_discovery_ids=tuple(
                        str(v)
                        for v in (item.get("source_discovery_ids") or [])
                    ),
                )
            )
        return seeds

    async def materialize_task_candidates(
        self,
        resources,
        reality,
        existing_tasks,
        capabilities,
        seeds,
        accepted_candidates=None,
    ):
        parsed = await self._chat_json(
            role_key="task_discovery",
            input_payload={
                "discovery_phase": "materialize",
                "current_resources": resources,
                "current_reality": reality,
                "effective_existing_tasks": existing_tasks,
                "current_capabilities": capabilities,
                "task_seeds": seeds,
                "first_pass_accepted_candidates": (
                    accepted_candidates or []
                ),
            },
            contract={
                "candidates": [
                    {
                        "task_identity": "string",
                        "reality_id": "string",
                        "description": "string",
                        "reality_basis": "string",
                        "expected_reality_result": "string",
                        "user_value": "string",
                        "execution_steps": ["string"],
                        "work_relation": "string",
                        "reality_basis_refs": ["string"],
                        "identity_anchor_refs": ["string"],
                        "required_capability_ids": ["string"],
                    }
                ]
            },
        )
        return self._task_candidates_from_payload(parsed)

    def _task_candidates_from_payload(self, parsed):
        raw = parsed.get("candidates") or []
        if not isinstance(raw, list):
            raise OllamaResponseError(
                "Task Discovery candidates 必须是 array。"
            )
        out = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            user_value = str(item.get("user_value") or "").strip()
            steps = item.get("execution_steps") or []
            if not user_value:
                continue
            if (
                not isinstance(steps, list)
                or not steps
                or not all(str(step).strip() for step in steps)
            ):
                continue
            out.append(
                TaskCandidate(
                    task_identity=str(item.get("task_identity") or ""),
                    reality_id=str(item.get("reality_id") or ""),
                    description=str(item.get("description") or ""),
                    reality_basis=str(item.get("reality_basis") or ""),
                    expected_reality_result=str(
                        item.get("expected_reality_result") or ""
                    ),
                    user_value=user_value,
                    execution_steps=tuple(
                        str(value).strip() for value in steps
                    ),
                    work_relation=str(item.get("work_relation") or ""),
                    reality_basis_refs=tuple(
                        str(value)
                        for value in (item.get("reality_basis_refs") or [])
                    ),
                    identity_anchor_refs=tuple(
                        str(value)
                        for value in (item.get("identity_anchor_refs") or [])
                    ),
                    required_capability_ids=tuple(
                        str(value)
                        for value in (item.get("required_capability_ids") or [])
                    ),
                )
            )
        return out

    async def discover_task_candidates(
        self,
        resources,
        reality,
        existing_tasks,
        capabilities,
        thinking_dimensions=None,
        accepted_candidates=None,
    ):
        seeds = await self.discover_task_seeds(
            resources=resources,
            reality=reality,
            existing_tasks=existing_tasks,
            capabilities=capabilities,
            thinking_dimensions=thinking_dimensions,
            accepted_candidates=accepted_candidates,
        )
        if not seeds:
            return []
        candidates = []
        for seed in seeds:
            materialized = await self.materialize_task_candidates(
                resources=resources,
                reality=reality,
                existing_tasks=existing_tasks,
                capabilities=capabilities,
                seeds=[seed],
                accepted_candidates=accepted_candidates,
            )
            candidates.extend(
                list(materialized or [])
            )
        return candidates

    async def repair_candidate_fields(
        self,
        resources,
        reality,
        existing_tasks,
        capabilities,
        candidate,
        field_issues,
    ):
        parsed = await self._chat_json(
            role_key="task_discovery",
            input_payload={
                "discovery_phase": "repair",
                "current_resources": resources,
                "current_reality": reality,
                "effective_existing_tasks": existing_tasks,
                "current_capabilities": capabilities,
                "candidate": candidate,
                "field_issues": field_issues,
            },
            contract={
                "description": "string",
                "expected_reality_result": "string",
                "user_value": "string",
                "execution_steps": ["string"],
            },
        )
        return CandidateFieldRepair(
            description=str(parsed.get("description") or "").strip(),
            expected_reality_result=str(
                parsed.get("expected_reality_result") or ""
            ).strip(),
            user_value=str(parsed.get("user_value") or "").strip(),
            execution_steps=tuple(
                str(step).strip()
                for step in (parsed.get("execution_steps") or [])
                if str(step).strip()
            ),
        )

    async def expand_thinking_dimensions(
        self,
        resources,
        reality,
        existing_tasks,
        capabilities,
        accepted_candidates,
        rejected_contexts=None,
    ):
        parsed = await self._chat_json(
            role_key="task_coverage_expansion",
            input_payload={
                "current_resources": resources,
                "current_reality": reality,
                "effective_existing_tasks": (
                    existing_tasks
                ),
                "current_capabilities": capabilities,
                "first_pass_accepted_candidates": (
                    accepted_candidates
                ),
                "first_pass_rejected_contexts": (
                    rejected_contexts or []
                ),
            },
            contract={
                "dimensions": [
                    {
                        "dimension_id": "string",
                        "focus": "string",
                        "user_question": "string",
                        "value_reason": "string",
                        "independence_reason": "string",
                        "reality_basis_refs": [
                            "string"
                        ],
                        "relevant_capability_ids": [
                            "string"
                        ],
                    }
                ]
            },
        )

        raw_dimensions = (
            parsed.get("dimensions")
            or []
        )
        if not isinstance(
            raw_dimensions,
            list,
        ):
            raise OllamaResponseError(
                "Task Coverage Expansion "
                "dimensions 必须是 array。"
            )

        dimensions = []
        for item in raw_dimensions:
            if not isinstance(item, dict):
                raise OllamaResponseError(
                    "Coverage Dimension 必须是 object。"
                )

            dimensions.append(
                CoverageDimension(
                    dimension_id=str(
                        item.get(
                            "dimension_id",
                            "",
                        )
                    ),
                    focus=str(
                        item.get(
                            "focus",
                            "",
                        )
                    ),
                    user_question=str(
                        item.get(
                            "user_question",
                            "",
                        )
                    ),
                    value_reason=str(
                        item.get(
                            "value_reason",
                            "",
                        )
                    ),
                    independence_reason=str(
                        item.get(
                            "independence_reason",
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
                    relevant_capability_ids=tuple(
                        str(value)
                        for value in (
                            item.get(
                                "relevant_capability_ids"
                            )
                            or []
                        )
                    ),
                )
            )

        return dimensions

    async def destructive_review_candidate(
        self,
        resources,
        reality,
        candidate,
        existing_tasks,
        capabilities,
    ):
        parsed = await self._chat_json(
            role_key="task_candidate_audit",
            input_payload={
                "current_resources": resources,
                "current_reality": reality,
                "candidate": candidate,
                "effective_existing_tasks": existing_tasks,
                "current_capabilities": capabilities,
            },
            contract={
                "core_valid": "boolean",
                "repair_required": "boolean",
                "field_issues": ["string"],
                "challenge": "string",
                "evidence": ["string"],
                "reason": "string",
            },
        )
        return CandidateReview(
            candidate_id=candidate.candidate_id,
            keep=bool(parsed.get("core_valid")),
            repair_required=bool(parsed.get("repair_required")),
            field_issues=tuple(
                str(value)
                for value in (parsed.get("field_issues") or [])
            ),
            challenge=str(parsed.get("challenge") or ""),
            evidence=tuple(
                str(value)
                for value in (parsed.get("evidence") or [])
            ),
            reason=str(parsed.get("reason") or ""),
        )

    async def destructive_review_candidate_set(
        self,
        resources,
        reality,
        candidates,
        existing_tasks,
        capabilities,
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
                "current_resources": resources,
                "current_reality": reality,
                "candidates": candidates,
                "effective_existing_tasks": (
                    existing_tasks
                ),
                "current_capabilities": capabilities,
            },
            contract={
                "keep_candidate_ids": [
                    "string"
                ],
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
                "Candidate Set Audit 返回未知 "
                "candidate_id："
                + ", ".join(
                    sorted(unknown)
                )
            )

        return CandidateSetReview(
            keep_candidate_ids=keep_ids,
            challenge=str(
                parsed.get(
                    "challenge"
                )
                or ""
            ),
            evidence=tuple(
                str(value)
                for value in (
                    parsed.get(
                        "evidence"
                    )
                    or []
                )
            ),
            reason=str(
                parsed.get(
                    "reason"
                )
                or ""
            ),
        )

    async def review_final_task_reality(
        self,
        resources,
        reality,
        capabilities,
        task,
    ):
        parsed = await self._chat_json(
            role_key="task_reality_validity",
            input_payload={
                "current_resources": resources,
                "current_reality": reality,
                "current_capabilities": capabilities,
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

    # ---- first-step chain: project -> problem / value / demand -> task ----

    async def assign_resources_to_projects(self, projects, resources, reality):
        parsed = await self._chat_json(
            role_key="project_assignment",
            input_payload={
                "projects": projects,
                "current_resources": resources,
                "current_reality": reality,
            },
            contract=skill_chain_io.ASSIGNMENT_CONTRACT,
        )
        return skill_chain_io.assignments_from_payload(parsed)

    async def discover_project_problems(
        self, project, resources, reality, capabilities, existing_tasks
    ):
        parsed = await self._chat_json(
            role_key="problem_discovery",
            input_payload={
                "project": project,
                "current_resources": resources,
                "current_reality": reality,
                "current_capabilities": capabilities,
                "effective_existing_tasks": existing_tasks,
            },
            contract=skill_chain_io.PROBLEMS_CONTRACT,
        )
        return skill_chain_io.problems_from_payload(parsed)

    async def discover_project_values(
        self, project, resources, reality, capabilities, existing_tasks
    ):
        parsed = await self._chat_json(
            role_key="value_discovery",
            input_payload={
                "project": project,
                "current_resources": resources,
                "current_reality": reality,
                "current_capabilities": capabilities,
                "effective_existing_tasks": existing_tasks,
            },
            contract=skill_chain_io.VALUES_CONTRACT,
        )
        return skill_chain_io.values_from_payload(parsed)

    async def discover_project_demands(
        self, project, resources, reality, capabilities
    ):
        parsed = await self._chat_json(
            role_key="demand_discovery",
            input_payload={
                "project": project,
                "current_resources": resources,
                "current_reality": reality,
                "current_capabilities": capabilities,
            },
            contract=skill_chain_io.DEMANDS_CONTRACT,
        )
        return skill_chain_io.demands_from_payload(parsed)

    async def plan_project_themes(
        self,
        project,
        resources,
        reality,
        capabilities,
        fixed_themes,
        previous_theme_yield,
    ):
        parsed = await self._chat_json(
            role_key="theme_planner",
            input_payload={
                "project": project,
                "current_resources": resources,
                "current_reality": reality,
                "current_capabilities": capabilities,
                "fixed_themes": list(fixed_themes),
                "previous_theme_yield": dict(previous_theme_yield or {}),
            },
            contract=skill_chain_io.THEME_PLAN_CONTRACT,
        )
        return skill_chain_io.theme_plan_from_payload(parsed)

    async def generate_theme_tasks(
        self,
        project,
        theme,
        theme_kind,
        theme_instruction,
        resource_info,
        capability_info,
        resources,
        reality,
        capabilities,
        problems,
        values,
        demands,
        existing_tasks,
    ):
        parsed = await self._chat_json(
            role_key="theme_task_generation",
            input_payload={
                "project": project,
                "theme": theme,
                "theme_kind": theme_kind,
                "theme_instruction": theme_instruction,
                "resource_info": resource_info,
                "capability_info": capability_info,
                "current_resources": resources,
                "current_reality": reality,
                "current_capabilities": capabilities,
                "problems": problems,
                "value_opportunities": values,
                "capability_voids": demands,
                "effective_existing_tasks": existing_tasks,
            },
            contract=skill_chain_io.THEME_TASKS_CONTRACT,
        )
        return skill_chain_io.theme_tasks_from_payload(parsed)
