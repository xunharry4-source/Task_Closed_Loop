from __future__ import annotations

import asyncio
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, time as _time
from decimal import Decimal
import json
import os
from pathlib import Path
from typing import Any

from task_closed_loop.llm.debug import LLMDebugPrinter
from task_closed_loop.model_io import (
    from_model_output_schema,
    to_model_input,
    to_model_schema,
)
from task_closed_loop.llm.prompt_registry import PromptRegistry
from task_closed_loop.llm.prompt_template import build_role_prompt
from task_closed_loop.llm import skill_chain_io
from task_closed_loop.llm.prompt_cache import PromptRequestCache
from task_closed_loop.reality.models import RealitySnapshot
from task_closed_loop.tasks.generation_models import (
    CandidateFailureContext,
    CandidateFieldRepair,
    CandidateFieldReview,
    CoverageDimension,
    DiscoverySignal,
    TaskOutcomeRecord,
    TaskSeed,
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

    # YAML turns a bare 2026-09-12 into datetime.date, which json.dumps rejects.
    # date must be checked alongside datetime (datetime is a subclass of date).
    if isinstance(value, (datetime, date, _time)):
        return value.isoformat()

    if isinstance(value, Decimal):
        return float(value)

    if isinstance(value, dict):
        return {
            str(key): _jsonable(item)
            for key, item in value.items()
        }

    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]

    if isinstance(value, (str, int, float, bool)) or value is None:
        return value

    # Anything else would crash json.dumps and take the whole run down; a real
    # resource payload is not worth losing over an exotic scalar type.
    return str(value)


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
        debugger: LLMDebugPrinter | None = None,
        prompt_cache: PromptRequestCache | None = None,
    ):
        model = str(model or "").strip()
        if not model:
            raise GeminiConfigurationError(
                "model 未配置。"
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

    def _build_prompt(
        self,
        role_key: str,
        input_payload: dict[str, Any],
    ):
        """提示词（内置或用户自己写的）+ `{{变量名}}` 替换。

        模板自己写了输入，`include_input` 就是 False，Host 不再追加【本轮输入】。
        """

        prompt_name = self.roles.get(role_key, role_key)
        return build_role_prompt(
            self.prompts.template(prompt_name),
            role_key=role_key,
            payload=_jsonable(input_payload),
        )

    def _create_interaction(
        self,
        *,
        role_key: str,
        input_payload: dict[str, Any],
        schema: dict[str, Any],
    ):
        built = self._build_prompt(role_key, input_payload)
        input_text = (
            built.text
            + (
                "\n\n【本轮输入】\n"
                + json.dumps(
                    _jsonable(input_payload),
                    ensure_ascii=False,
                    indent=2,
                )
                if built.include_input
                else ""
            )
            + "\n\n根据本轮输入完成上述职责。"
            + "输出由 response_format 约束为 JSON。"
        )

        response_format = [
            {
                "type": "text",
                "mime_type": "application/json",
                "schema": schema,
            }
        ]

        if self.prompt_cache is not None:
            self.prompt_cache.record(
                provider="gemini",
                model=self.model,
                role_key=role_key,
                prompt=input_text,
                metadata={
                    "transport": "genai_interactions_create",
                    "endpoint": "interactions.create",
                },
            )

        self.debugger.request(
            adapter="gemini",
            model=self.model,
            role=role_key,
            prompt=input_text,
            response_contract=response_format,
        )

        try:
            return self.client.interactions.create(
                model=self.model,
                input=input_text,
                response_format=response_format,
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
        # The model works with readable names; domain parsing below keeps internal ones.
        input_payload = to_model_input(input_payload)
        schema = to_model_schema(schema)
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

        if self.prompt_cache is not None:
            self.prompt_cache.record_response(
                provider=getattr(self, "provider_name", "gemini"),
                model=self.model,
                role_key=role_key,
                response=output_text,
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

        return from_model_output_schema(parsed, schema)

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

    async def discover_need_opportunities(
        self,
        resources,
        reality,
        existing_tasks,
        all_existing_tasks,
        capabilities,
    ):
        discovery_schema = _object_schema(
            {
                "discovery_id": {"type": "string"},
                "discovery_kind": {"type": "string"},
                "reality_relation": {"type": "string"},
                "user_relevance_hypothesis": {"type": "string"},
                "desired_change_or_answer": {"type": "string"},
                "independence_reason": {"type": "string"},
                "reality_basis_refs": _STRING_ARRAY,
                "relevant_capability_ids": _STRING_ARRAY,
            },
            [
                "discovery_id",
                "discovery_kind",
                "reality_relation",
                "user_relevance_hypothesis",
                "desired_change_or_answer",
                "independence_reason",
                "reality_basis_refs",
                "relevant_capability_ids",
            ],
        )
        schema = _object_schema(
            {
                "discoveries": {
                    "type": "array",
                    "items": discovery_schema,
                }
            },
            ["discoveries"],
        )
        parsed = await self._interaction_json(
            role_key="need_opportunity_discovery",
            input_payload={
                "current_resources": resources,
                "current_reality": reality,
                "effective_existing_tasks": existing_tasks,
                "all_existing_tasks": all_existing_tasks,
                "current_capabilities": capabilities,
            },
            schema=schema,
        )
        raw = parsed.get("discoveries") or []
        if not isinstance(raw, list):
            raise GeminiResponseError(
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
                        for v in (item.get("reality_basis_refs") or [])
                    ),
                    relevant_capability_ids=tuple(
                        str(v)
                        for v in (item.get("relevant_capability_ids") or [])
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
        seed_schema = _object_schema(
            {
                "seed_id": {"type": "string"},
                "work_relation": {"type": "string"},
                "result_goal": {"type": "string"},
                "user_value_hypothesis": {"type": "string"},
                "independence_reason": {"type": "string"},
                "reality_basis_refs": _STRING_ARRAY,
                "required_capability_ids": _STRING_ARRAY,
                "identity_anchor_refs": _STRING_ARRAY,
                "parent_task_ids": _STRING_ARRAY,
                "parent_outcome_ids": _STRING_ARRAY,
                "proliferation_reason": {"type": "string"},
            },
            [
                "seed_id",
                "work_relation",
                "result_goal",
                "user_value_hypothesis",
                "independence_reason",
                "reality_basis_refs",
                "required_capability_ids",
                "parent_task_ids",
                "parent_outcome_ids",
                "proliferation_reason",
            ],
        )
        schema = _object_schema(
            {
                "seeds": {
                    "type": "array",
                    "items": seed_schema,
                }
            },
            ["seeds"],
        )
        parsed = await self._interaction_json(
            role_key="task_proliferation",
            input_payload={
                "current_resources": resources,
                "current_reality": reality,
                "effective_existing_tasks": existing_tasks,
                "all_existing_tasks": all_existing_tasks,
                "current_capabilities": capabilities,
                "task_outcomes": task_outcomes,
            },
            schema=schema,
        )
        raw = parsed.get("seeds") or []
        if not isinstance(raw, list):
            raise GeminiResponseError(
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
        seed_schema = _object_schema(
            {
                "seed_id": {"type": "string"},
                "work_relation": {"type": "string"},
                "result_goal": {"type": "string"},
                "user_value_hypothesis": {"type": "string"},
                "independence_reason": {"type": "string"},
                "reality_basis_refs": _STRING_ARRAY,
                "required_capability_ids": _STRING_ARRAY,
                "source_discovery_ids": _STRING_ARRAY,
            },
            [
                "seed_id",
                "work_relation",
                "result_goal",
                "user_value_hypothesis",
                "independence_reason",
                "reality_basis_refs",
                "required_capability_ids",
            ],
        )
        schema = _object_schema(
            {
                "seeds": {
                    "type": "array",
                    "items": seed_schema,
                }
            },
            ["seeds"],
        )

        parsed = await self._interaction_json(
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
            schema=schema,
        )

        raw = parsed.get("seeds") or []
        if not isinstance(raw, list):
            raise GeminiResponseError(
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
                        for v in (
                            item.get("reality_basis_refs") or []
                        )
                    ),
                    required_capability_ids=tuple(
                        str(v)
                        for v in (
                            item.get("required_capability_ids") or []
                        )
                    ),
                    origin_type="reality_discovery",
                    source_discovery_ids=tuple(
                        str(v)
                        for v in (
                            item.get("source_discovery_ids") or []
                        )
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
        candidate_schema = _object_schema(
            {
                "task_identity": {"type": "string"},
                "reality_id": {"type": "string"},
                "description": {"type": "string"},
                "reality_basis": {"type": "string"},
                "expected_reality_result": {"type": "string"},
                "user_value": {"type": "string"},
                "execution_steps": _STRING_ARRAY,
                "work_relation": {"type": "string"},
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
                "user_value",
                "execution_steps",
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
            schema=schema,
        )
        return self._task_candidates_from_payload(parsed)

    def _task_candidates_from_payload(self, parsed):
        raw_candidates = parsed.get("candidates") or []
        if not isinstance(raw_candidates, list):
            raise GeminiResponseError(
                "Task Discovery candidates 必须是 array。"
            )

        candidates = []
        for item in raw_candidates:
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

            candidates.append(
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
                        for value in (
                            item.get("reality_basis_refs") or []
                        )
                    ),
                    identity_anchor_refs=tuple(
                        str(value)
                        for value in (
                            item.get("identity_anchor_refs") or []
                        )
                    ),
                    required_capability_ids=tuple(
                        str(value)
                        for value in (
                            item.get("required_capability_ids") or []
                        )
                    ),
                )
            )
        return candidates

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
        schema = _object_schema(
            {
                "description": {"type": "string"},
                "expected_reality_result": {"type": "string"},
                "user_value": {"type": "string"},
                "execution_steps": _STRING_ARRAY,
            },
            [
                "description",
                "expected_reality_result",
                "user_value",
                "execution_steps",
            ],
        )
        parsed = await self._interaction_json(
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
            schema=schema,
        )
        steps = parsed.get("execution_steps") or []
        return CandidateFieldRepair(
            description=str(parsed.get("description") or "").strip(),
            expected_reality_result=str(
                parsed.get("expected_reality_result") or ""
            ).strip(),
            user_value=str(parsed.get("user_value") or "").strip(),
            execution_steps=tuple(
                str(step).strip() for step in steps if str(step).strip()
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
        dimension_schema = _object_schema(
            {
                "dimension_id": {
                    "type": "string",
                },
                "focus": {
                    "type": "string",
                },
                "user_question": {
                    "type": "string",
                },
                "value_reason": {
                    "type": "string",
                },
                "independence_reason": {
                    "type": "string",
                },
                "reality_basis_refs": (
                    _STRING_ARRAY
                ),
                "relevant_capability_ids": (
                    _STRING_ARRAY
                ),
            },
            [
                "dimension_id",
                "focus",
                "user_question",
                "value_reason",
                "independence_reason",
                "reality_basis_refs",
                "relevant_capability_ids",
            ],
        )

        schema = _object_schema(
            {
                "dimensions": {
                    "type": "array",
                    "items": dimension_schema,
                }
            },
            ["dimensions"],
        )

        parsed = await self._interaction_json(
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
            schema=schema,
        )

        raw_dimensions = (
            parsed.get("dimensions") or []
        )
        if not isinstance(
            raw_dimensions,
            list,
        ):
            raise GeminiResponseError(
                "Task Coverage Expansion "
                "dimensions 必须是 array。"
            )

        dimensions = []
        for item in raw_dimensions:
            if not isinstance(item, dict):
                raise GeminiResponseError(
                    "Coverage Dimension 必须是 object。"
                )

            dimensions.append(
                CoverageDimension(
                    dimension_id=str(
                        item.get(
                            "dimension_id"
                        )
                        or ""
                    ),
                    focus=str(
                        item.get("focus")
                        or ""
                    ),
                    user_question=str(
                        item.get(
                            "user_question"
                        )
                        or ""
                    ),
                    value_reason=str(
                        item.get(
                            "value_reason"
                        )
                        or ""
                    ),
                    independence_reason=str(
                        item.get(
                            "independence_reason"
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
        schema = _object_schema(
            {
                "core_valid": {"type": "boolean"},
                "challenge": {"type": "string"},
                "evidence": _STRING_ARRAY,
                "reason": {"type": "string"},
            },
            [
                "core_valid",
                "challenge",
                "evidence",
                "reason",
            ],
        )
        parsed = await self._interaction_json(
            role_key="task_candidate_audit",
            input_payload={
                "current_resources": resources,
                "current_reality": reality,
                "candidate": candidate,
                "effective_existing_tasks": existing_tasks,
                "current_capabilities": capabilities,
            },
            schema=schema,
        )
        return CandidateReview(
            candidate_id=candidate.candidate_id,
            keep=bool(parsed.get("core_valid")),
            challenge=str(parsed.get("challenge") or ""),
            evidence=tuple(
                str(value)
                for value in (parsed.get("evidence") or [])
            ),
            reason=str(parsed.get("reason") or ""),
        )

    async def review_candidate_fields(
        self,
        resources,
        reality,
        candidate,
        existing_tasks,
        capabilities,
    ):
        schema = _object_schema(
            {
                "repair_required": {"type": "boolean"},
                "field_issues": _STRING_ARRAY,
                "challenge": {"type": "string"},
                "evidence": _STRING_ARRAY,
                "reason": {"type": "string"},
            },
            [
                "repair_required",
                "field_issues",
                "challenge",
                "evidence",
                "reason",
            ],
        )
        parsed = await self._interaction_json(
            role_key="task_candidate_field_audit",
            input_payload={
                "current_resources": resources,
                "current_reality": reality,
                "candidate": candidate,
                "effective_existing_tasks": existing_tasks,
                "current_capabilities": capabilities,
            },
            schema=schema,
        )
        return CandidateFieldReview(
            candidate_id=candidate.candidate_id,
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
                "current_resources": resources,
                "current_reality": reality,
                "candidates": candidates,
                "effective_existing_tasks": (
                    existing_tasks
                ),
                "current_capabilities": capabilities,
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
        resources,
        reality,
        capabilities,
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
                "current_resources": resources,
                "current_capabilities": capabilities,
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

    # ---- first-step chain: project -> problem / value / demand -> task ----

    async def discover_projects(self, resources, capabilities, known_projects):
        parsed = await self._interaction_json(
            role_key="project_discovery",
            input_payload={
                "current_resources": resources,
                "current_capabilities": capabilities,
                "known_projects": list(known_projects or []),
            },
            schema=skill_chain_io.PROJECT_SCHEMA,
        )
        return skill_chain_io.projects_from_payload(parsed)

    async def assign_resources_to_projects(self, projects, resources, reality):
        parsed = await self._interaction_json(
            role_key="project_assignment",
            input_payload={
                "projects": projects,
                "current_resources": resources,
                "current_reality": reality,
            },
            schema=skill_chain_io.ASSIGNMENT_SCHEMA,
        )
        return skill_chain_io.assignments_from_payload(parsed)

    async def discover_project_problems(
        self, project, resources, capabilities, existing_tasks
    ):
        parsed = await self._interaction_json(
            role_key="problem_discovery",
            input_payload={
                "project": project,
                "current_resources": resources,
                "current_capabilities": capabilities,
                "effective_existing_tasks": existing_tasks,
            },
            schema=skill_chain_io.PROBLEMS_SCHEMA,
        )
        return skill_chain_io.problems_from_payload(parsed)

    async def discover_project_values(
        self, project, resources, capabilities, existing_tasks
    ):
        parsed = await self._interaction_json(
            role_key="value_discovery",
            input_payload={
                "project": project,
                "current_resources": resources,
                "current_capabilities": capabilities,
                "effective_existing_tasks": existing_tasks,
            },
            schema=skill_chain_io.VALUES_SCHEMA,
        )
        return skill_chain_io.values_from_payload(parsed)

    async def discover_project_demands(
        self, project, resources, capabilities
    ):
        parsed = await self._interaction_json(
            role_key="demand_discovery",
            input_payload={
                "project": project,
                "current_resources": resources,
                "current_capabilities": capabilities,
            },
            schema=skill_chain_io.DEMANDS_SCHEMA,
        )
        return skill_chain_io.demands_from_payload(parsed)

    async def plan_project_themes(
        self,
        project,
        resources,
        capabilities,
        problems,
        values,
        demands,
        fixed_themes,
        previous_theme_yield,
    ):
        parsed = await self._interaction_json(
            role_key="theme_planner",
            input_payload={
                "project": project,
                "current_resources": resources,
                "current_capabilities": capabilities,
                "problems": problems,
                "value_opportunities": values,
                "capability_voids": demands,
                "fixed_themes": list(fixed_themes),
                "previous_theme_yield": dict(previous_theme_yield or {}),
            },
            schema=skill_chain_io.THEME_PLAN_SCHEMA,
        )
        return skill_chain_io.theme_plan_from_payload(parsed)

    async def generate_theme_tasks(
        self,
        project,
        theme,
        theme_kind,
        theme_instruction,
        resource_info,
        resources,
        capabilities,
        existing_tasks,
    ):
        parsed = await self._interaction_json(
            role_key="theme_task_generation",
            input_payload={
                "project": project,
                "theme": theme,
                "theme_kind": theme_kind,
                "theme_instruction": theme_instruction,
                "resource_info": resource_info,
                "current_resources": resources,
                "current_capabilities": capabilities,
                "effective_existing_tasks": existing_tasks,
            },
            schema=skill_chain_io.THEME_TASKS_SCHEMA,
        )
        return skill_chain_io.theme_tasks_from_payload(parsed)
