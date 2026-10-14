"""One reference grammar for everything a model cites in Stage 3-7.

A model grounds a finding, task idea or task in its input by citing it. Previously each
validator had its own idea of what a citation looks like (exact identity, lenient
prefix, exact set difference), none of which was ever told to the model, so a
precise citation such as `current_resources[trading_data].payload...` was thrown away.

The grammar is `<type>:<identity>[#<field path>]`:

    resource:<resource_id>[#path]        an entry of `resources`
    reality:current[#path]               the `reality` object
    task_outcome:<outcome_id>[#path]     an entry of `task_outcomes`
    capability:<capability_id>           an observable capability (no path)
    <observed object ref>                verbatim, e.g. gmail:message:abc (no path)

A field path is resolved against the object exactly as the model saw it in its input
(`model_io.to_model_view`), so whatever the model can see it can cite, and whatever
does not exist is rejected. Rejections always say how to write the citation instead.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
from typing import Any, Iterable

from task_closed_loop.integration.models import CapabilityDescriptor, ResourceSnapshot
from task_closed_loop.model_io import FIELD_MAP, to_model_view, to_plain
from task_closed_loop.reality.models import RealitySnapshot

RESOURCE = "resource"
REALITY = "reality"
TASK_OUTCOME = "task_outcome"
CAPABILITY = "capability"
OBJECT = "object"

TYPED_KINDS = (RESOURCE, REALITY, TASK_OUTCOME, CAPABILITY)
REALITY_IDENTITY = "current"

_OUTCOME_RESOURCE_PREFIX = "task_outcome:"
_MAX_LISTED = 12


@dataclass(frozen=True)
class Reference:
    raw: str
    kind: str
    identity: str
    path: str = ""

    @property
    def key(self) -> tuple[str, str]:
        return (self.kind, self.identity)

    @property
    def without_path(self) -> str:
        if self.kind == OBJECT:
            return self.identity
        return f"{self.kind}:{self.identity}"


def parse_reference(raw: Any) -> Reference:
    text = str(raw).strip()
    for kind in TYPED_KINDS:
        prefix = f"{kind}:"
        if text.startswith(prefix):
            body = text[len(prefix):]
            identity, _, path = body.partition("#")
            return Reference(raw=text, kind=kind, identity=identity.strip(), path=path.strip())
    return Reference(raw=text, kind=OBJECT, identity=text)


def reference_key(raw: Any) -> tuple[str, str]:
    """Identity of what a citation points at, ignoring any field path."""

    return parse_reference(raw).key


def reference_without_path(raw: Any) -> str:
    return parse_reference(raw).without_path


# ---------------------------------------------------------------------------
# Field paths
# ---------------------------------------------------------------------------


class _PathSyntaxError(ValueError):
    pass


def _tokenize_path(path: str) -> list[tuple[str, Any]]:
    """Split `a.b[3]["c.d"]` into [("seg","a"),("seg","b"),("idx",3),("key","c.d")]."""

    tokens: list[tuple[str, Any]] = []
    i = 0
    n = len(path)
    expect_segment = True
    while i < n:
        ch = path[i]
        if ch == ".":
            if expect_segment:
                raise _PathSyntaxError("路径中出现了空的字段名（连续的 . 或以 . 开头）。")
            expect_segment = True
            i += 1
            continue
        if ch == "[":
            end = path.find("]", i)
            if path[i + 1 : i + 2] == '"':
                close = path.find('"]', i + 2)
                if close < 0:
                    raise _PathSyntaxError('["…"] 没有闭合。')
                try:
                    key = json.loads(path[i + 1 : close + 1])
                except json.JSONDecodeError as exc:
                    raise _PathSyntaxError(f'["…"] 不是合法的字符串：{exc}') from exc
                tokens.append(("key", str(key)))
                i = close + 2
            else:
                if end < 0:
                    raise _PathSyntaxError("[ 没有闭合。")
                inner = path[i + 1 : end].strip()
                if not re.fullmatch(r"-?\d+", inner):
                    raise _PathSyntaxError(
                        f"[{inner}] 不是整数下标；字段名请用 .名称，含特殊字符的字段名用 [\"名称\"]。"
                    )
                tokens.append(("idx", int(inner)))
                i = end + 1
            expect_segment = False
            continue
        if not expect_segment:
            raise _PathSyntaxError(f"位置 {i} 缺少 . 或 [ 分隔。")
        start = i
        while i < n and path[i] not in ".[]":
            i += 1
        if path[start:i] == "":
            raise _PathSyntaxError(f"位置 {start} 出现了多余的 ]。")
        tokens.append(("seg", path[start:i]))
        expect_segment = False
    if expect_segment and tokens:
        raise _PathSyntaxError("路径以 . 结尾。")
    return tokens


def _describe_keys(value: Any) -> str:
    if isinstance(value, dict):
        keys = [str(key) for key in value]
        shown = ", ".join(keys[:_MAX_LISTED])
        more = f" 等 {len(keys)} 个" if len(keys) > _MAX_LISTED else ""
        return f"这里可用的字段：{shown}{more}" if keys else "这里是空对象"
    if isinstance(value, list):
        return f"这里是长度为 {len(value)} 的数组，下标用 [0]…[{max(len(value) - 1, 0)}]"
    return f"这里已经是标量值（{type(value).__name__}），不能再往下取"


def resolve_path(view: Any, path: str) -> str | None:
    """Return None when `path` exists in `view`, otherwise a readable reason.

    Field names that themselves contain dots (file names such as `AAPL.csv`) are
    matched by joining consecutive segments; this never accepts a path that does not
    exist in the data.
    """

    if not path:
        return None
    try:
        tokens = _tokenize_path(path)
    except _PathSyntaxError as exc:
        return f"字段路径语法错误：{exc}"

    current = view
    walked = ""
    i = 0
    while i < len(tokens):
        kind, value = tokens[i]
        if kind == "idx":
            if isinstance(current, list) and -len(current) <= value < len(current):
                current = current[value]
                walked += f"[{value}]"
                i += 1
                continue
            if isinstance(current, dict) and str(value) in current:
                current = current[str(value)]
                walked += f"[{value}]"
                i += 1
                continue
            return f"路径 {walked or '<根>'} 之后没有 [{value}]；{_describe_keys(current)}。"

        if kind == "key":
            if isinstance(current, dict) and value in current:
                current = current[value]
                walked += f'["{value}"]'
                i += 1
                continue
            return f'路径 {walked or "<根>"} 之后没有字段 "{value}"；{_describe_keys(current)}。'

        # bare segment
        if isinstance(current, list) and re.fullmatch(r"\d+", value):
            index = int(value)
            if index < len(current):
                current = current[index]
                walked += f"[{index}]"
                i += 1
                continue
        if isinstance(current, dict):
            if value in current:
                current = current[value]
                walked += ("." if walked else "") + value
                i += 1
                continue
            joined = value
            matched = False
            j = i + 1
            while j < len(tokens) and tokens[j][0] == "seg":
                joined = f"{joined}.{tokens[j][1]}"
                if joined in current:
                    current = current[joined]
                    walked += ("." if walked else "") + joined
                    i = j + 1
                    matched = True
                    break
                j += 1
            if matched:
                continue
        return f"路径 {walked or '<根>'} 之后没有字段 {value}；{_describe_keys(current)}。"
    return None


# ---------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------


def _listing(values: Iterable[str]) -> str:
    items = sorted({str(value) for value in values if str(value).strip()})
    if not items:
        return "（无）"
    shown = ", ".join(items[:_MAX_LISTED])
    return shown + (f" 等 {len(items)} 个" if len(items) > _MAX_LISTED else "")


def _split_head(text: str) -> tuple[str, str]:
    """`trading_data.payload[0]` -> (`trading_data`, `.payload[0]`)."""

    match = re.search(r"[.\[]", text)
    if not match:
        return text, ""
    return text[: match.start()], text[match.start():]


@dataclass
class ReferenceContext:
    reality: RealitySnapshot
    resources: dict[str, ResourceSnapshot]
    outcomes: dict[str, ResourceSnapshot]
    capabilities: dict[str, CapabilityDescriptor]
    allow_capability: bool
    outcome_records: dict[str, Any] = field(default_factory=dict)
    declared_object_refs: set[str] = field(default_factory=set)
    _views: dict[tuple[str, str], list[Any]] = field(default_factory=dict)

    @classmethod
    def build(
        cls,
        *,
        reality: RealitySnapshot,
        resources: Iterable[ResourceSnapshot] | None = None,
        capabilities: Iterable[CapabilityDescriptor] | None = None,
        allow_capability: bool = False,
        task_outcomes: Iterable[Any] | None = None,
    ) -> "ReferenceContext":
        plain_resources: dict[str, ResourceSnapshot] = {}
        outcomes: dict[str, ResourceSnapshot] = {}
        declared: set[str] = set()

        for resource in resources or ():
            resource_id = str(resource.resource_id).strip()
            if not resource_id:
                continue
            if (
                resource_id.startswith(_OUTCOME_RESOURCE_PREFIX)
                or str(resource.resource_type).strip() == "task_outcome"
            ):
                outcome_id = resource_id[len(_OUTCOME_RESOURCE_PREFIX):] if resource_id.startswith(
                    _OUTCOME_RESOURCE_PREFIX
                ) else resource_id
                outcomes[outcome_id] = resource
                if isinstance(resource.payload, dict):
                    for key in ("subject_refs", "evidence_refs", "effect_refs"):
                        for value in resource.payload.get(key) or ():
                            if str(value).strip():
                                declared.add(str(value).strip())
                continue
            plain_resources[resource_id] = resource

        records: dict[str, Any] = {}
        for record in task_outcomes or ():
            outcome_id = str(getattr(record, "outcome_id", "")).strip()
            if outcome_id:
                records[outcome_id] = record
                for key in ("subject_refs", "evidence_refs", "effect_refs"):
                    for value in getattr(record, key, ()) or ():
                        if str(value).strip():
                            declared.add(str(value).strip())

        for value in list(reality.evidence_refs or ()) + list(reality.effect_refs or ()):
            if str(value).strip():
                declared.add(str(value).strip())

        return cls(
            reality=reality,
            resources=plain_resources,
            outcomes=outcomes,
            capabilities={
                str(capability.capability_id): capability
                for capability in capabilities or ()
            },
            allow_capability=allow_capability,
            outcome_records=records,
            declared_object_refs=declared,
        )

    # -- views ---------------------------------------------------------------

    def _views_for(self, kind: str, identity: str) -> list[Any]:
        key = (kind, identity)
        if key in self._views:
            return self._views[key]
        views: list[Any] = []
        if kind == RESOURCE:
            views.append(to_model_view(self.resources[identity]))
        elif kind == REALITY:
            views.append(to_model_view(self.reality))
        elif kind == TASK_OUTCOME:
            resource = self.outcomes.get(identity)
            if resource is not None:
                views.append(to_plain(resource.payload))
            record = self.outcome_records.get(identity)
            if record is not None:
                views.append(to_model_view(record))
        self._views[key] = views
        return views

    def _path_problem(self, ref: Reference) -> str | None:
        if not ref.path:
            return None
        reasons = []
        for view in self._views_for(ref.kind, ref.identity):
            reason = resolve_path(view, ref.path)
            if reason is None:
                return None
            reasons.append(reason)
        return reasons[0] if reasons else "找不到可以解析字段路径的对象。"

    # -- checks --------------------------------------------------------------

    def _available_observers(self) -> list[str]:
        return [
            capability_id
            for capability_id, capability in self.capabilities.items()
            if str(capability.availability).lower() == "available" and capability.can_observe_state
        ]

    @staticmethod
    def _friendly_path(path: str) -> str:
        """Rewrite internal field names in a path the way the model sees them."""

        return re.sub(
            r"(?<![\w\"])([A-Za-z_][A-Za-z0-9_]*)(?![\w\"])",
            lambda match: FIELD_MAP.get(match.group(1), match.group(1)),
            path,
        )

    def _hint_for_untyped(self, text: str) -> str:
        head, rest = _split_head(text)
        rest_path = rest.lstrip(".")

        if head in ("current_resources", "resources", "task_outcomes"):
            kind = RESOURCE if head != "task_outcomes" else TASK_OUTCOME
            known = self.resources if kind == RESOURCE else {**self.outcomes, **self.outcome_records}
            match = re.match(r"\[\s*[\"']?([^\]\"']+)[\"']?\s*\]\.?(.*)$", rest)
            if match and match.group(1) in known:
                path = self._friendly_path(match.group(2))
                suggestion = f"{kind}:{match.group(1)}" + (f"#{path}" if path else "")
                return f"这是按输入段名写的路径，不是引用。要写成 {suggestion}（字段路径用 # 与身份分隔）。"
            label = "resource_id" if kind == RESOURCE else "outcome_id"
            return (
                f"这是按输入段名写的路径，不是引用。要写成 {kind}:<{label}>#<字段路径>，"
                f"身份写对象的 {label}，不要用数组下标；可用的 {label}：{_listing(known)}。"
            )

        if head in ("current_reality", "reality"):
            path = self._friendly_path(rest_path)
            suggestion = "reality:current" + (f"#{path}" if path else "")
            return f"这是按输入段名写的路径，不是引用。要写成 {suggestion}（字段路径用 # 与身份分隔）。"

        if head in ("current_capabilities", "capabilities"):
            return "这是按输入段名写的路径，不是引用。能力写成 capability:<capability_id>，不带字段路径。"

        for qualifier in ("fact:", "facts:", "evidence:", "effect:", "gap:"):
            if text.startswith(qualifier):
                return (
                    f"不支持 {qualifier} 前缀。现实里的内容写成 reality:current#<字段路径>，"
                    "例如 reality:current#facts 或 reality:current#gaps[0]。"
                )

        if head in self.resources:
            suffix = f"#{rest_path}" if rest_path else ""
            return f"缺少类型前缀。要写成 resource:{head}{suffix}。"
        if head in self.outcomes:
            suffix = f"#{rest_path}" if rest_path else ""
            return f"缺少类型前缀。要写成 task_outcome:{head}{suffix}。"
        if head in self.capabilities:
            return f"缺少类型前缀。要写成 capability:{head}。"
        if head == str(self.reality.reality_id).strip():
            suffix = f"#{rest_path}" if rest_path else ""
            return f"当前现实统一写成 reality:current{suffix}，不要使用 reality_id。"

        return (
            "不是可识别的引用，也不是输入中声明过的观察对象。必须写成以下之一："
            "resource:<resource_id>[#字段路径]、reality:current[#字段路径]、"
            "task_outcome:<outcome_id>[#字段路径]、capability:<capability_id>，"
            "或原样照抄 task_outcomes 的 subject_refs/evidence_refs/effect_refs、"
            "reality 的 evidence_refs/effect_refs 中的某一项。"
        )

    def check(self, raw: Any) -> str | None:
        """None when the citation is valid, otherwise why not and how to write it."""

        text = str(raw).strip()
        if not text:
            return "空引用。"
        if text in self.declared_object_refs:
            return None

        ref = parse_reference(text)

        if ref.kind == OBJECT:
            return self._hint_for_untyped(text)

        if not ref.identity:
            return f"{ref.kind}: 后面缺少身份。"

        if ref.kind == RESOURCE:
            if ref.identity.startswith(_OUTCOME_RESOURCE_PREFIX):
                outcome_id = ref.identity[len(_OUTCOME_RESOURCE_PREFIX):]
                suffix = f"#{ref.path}" if ref.path else ""
                return f"Outcome 统一写成 task_outcome:{outcome_id}{suffix}，不要写成 resource:task_outcome:…。"
            if ref.identity not in self.resources:
                head, rest = _split_head(ref.identity)
                if head in self.resources:
                    return (
                        f"字段路径必须用 # 与资源身份分隔：resource:{head}#{rest.lstrip('.')}"
                        + (f"#{ref.path}" if ref.path else "")
                        + "。"
                    )
                return (
                    f"resources 中没有 resource_id 为 {ref.identity} 的资源；"
                    f"可用的 resource_id：{_listing(self.resources)}。"
                )
            return self._path_problem(ref)

        if ref.kind == REALITY:
            if ref.identity != REALITY_IDENTITY:
                head, rest = _split_head(ref.identity)
                if head == REALITY_IDENTITY:
                    return f"字段路径必须用 # 分隔：reality:current#{rest.lstrip('.')}。"
                suffix = f"#{ref.path}" if ref.path else ""
                return f"当前现实只能写成 reality:current{suffix}，身份固定为 current。"
            return self._path_problem(ref)

        if ref.kind == TASK_OUTCOME:
            if ref.identity not in self.outcomes and ref.identity not in self.outcome_records:
                head, rest = _split_head(ref.identity)
                if head in self.outcomes or head in self.outcome_records:
                    return f"字段路径必须用 # 分隔：task_outcome:{head}#{rest.lstrip('.')}。"
                return (
                    f"当前输入中没有 outcome_id 为 {ref.identity} 的 Outcome；"
                    f"可用的 outcome_id：{_listing(list(self.outcomes) + list(self.outcome_records))}。"
                )
            return self._path_problem(ref)

        # capability
        if not self.allow_capability:
            return (
                "这一步不接受 capability: 作为依据；能力只说明能去观察，不说明现实已经是什么。"
                "请引用 resources / reality 中已经存在的内容。"
            )
        if ref.path:
            return f"capability 引用不带字段路径，写成 capability:{ref.identity}。"
        capability = self.capabilities.get(ref.identity)
        if capability is None:
            return f"capabilities 中没有 {ref.identity}；可用的 capability_id：{_listing(self.capabilities)}。"
        if str(capability.availability).lower() != "available" or not capability.can_observe_state:
            return (
                f"capability:{ref.identity} 不是当前可用、且能观察外部状态的能力，不能作为依据；"
                f"可以作为依据的能力：{_listing(self._available_observers())}。"
            )
        return None

    def problems(self, refs: Iterable[Any]) -> dict[str, str]:
        found: dict[str, str] = {}
        for raw in refs:
            text = str(raw).strip()
            reason = self.check(text)
            if reason is not None:
                found[text or "<空>"] = reason
        return found

    def check_anchor(self, raw: Any) -> str | None:
        """`about_object_refs`: a declared object ref verbatim, or resource:<id>."""

        text = str(raw).strip()
        if not text:
            return "空引用。"
        if text in self.declared_object_refs:
            return None
        ref = parse_reference(text)
        if ref.kind == RESOURCE and not ref.identity.startswith(_OUTCOME_RESOURCE_PREFIX):
            if ref.path:
                return f"about_object_refs 不带字段路径，写成 resource:{ref.identity}。"
            if ref.identity in self.resources:
                return None
        return (
            "about_object_refs 只能是 task_outcomes 中声明过的 subject_refs 原样，"
            f"或 resource:<resource_id>（不带字段路径）；可用的资源：{_listing('resource:' + r for r in self.resources)}。"
        )


def format_problems(problems: dict[str, str]) -> str:
    return "；".join(f"{ref} → {reason}" for ref, reason in sorted(problems.items()))
