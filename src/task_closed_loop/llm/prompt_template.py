"""用户提示词模板：`{{变量名}}` 替换。

提示词一个角色一个文件，放在 `config/prompts/<角色名>.md`（见 `prompt_registry.py`），
正文里用 `{{变量名}}` 取本轮输入里的东西。

**变量名在代码里写死**——就是下面的 `VARIABLES`，用户不能自己造新变量。
每个变量什么意思，写在**各自提示词文件开头的 `---` 说明块**里：那里只列这个角色本轮
真有的变量（verify 脚本比对说明块与代码，两边不一致就报错）。

规则只有三条：

1. `{{变量名}}` 换成那个变量的值：字符串原样插入，其它结构按 JSON（缩进 2）插入。
2. 变量名不存在，或这个角色本轮没有这项输入，直接报错——不会悄悄插入空值。
3. 模板自己写了 `{{输入}}` 或任意一个输入变量，Host 就不再追加【本轮输入】那一段；
   写了 `{{引用语法}}`，也不再追加引用语法。写了就是你自己安排，不重复塞第二份。
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any

# `{{ 名字 }}` 两侧空白允许
PLACEHOLDER = re.compile(r"\{\{\s*([^{}]*?)\s*\}\}")

# 三个特殊变量：不来自本轮输入的某一项
INPUT_NAMES = ("输入", "input")
CONTRACT_NAMES = ("引用语法", "reference_syntax")
ROLE_NAMES = ("角色", "role")


class PromptTemplateError(RuntimeError):
    pass


@dataclass(frozen=True)
class PromptVariable:
    """一个写死的变量名。

    `name` 是写进提示词的中文名，`alias` 是英文别名，两个都能用；
    `key` 是它在本轮输入里的字段名（也就是【本轮输入】那段 JSON 里的键）。
    """

    name: str
    alias: str
    key: str
    description: str
    note: str = ""


# 变量表：改这里就要同步改各提示词文件开头的 --- 说明块（verify 脚本会比对）
VARIABLES: tuple[PromptVariable, ...] = (
    PromptVariable("项目", "project", "project", "这个项目：id、名称、一句话说明（它是干嘛的、现在什么情况）"),
    PromptVariable("资源", "resources", "resources", "本项目的资源：第四、五步只给 id + summary（现在有什么、到什么程度），审核与旧链条给完整分析结果"),
    PromptVariable("功能", "capabilities", "capabilities", "可用功能：每条是功能名 function + identity（谁开发的、什么类型的工具），不含「能做什么」"),
    PromptVariable("资源信息", "resource_info", "resource_info", "主题规划那一步整理出来的资源说明（一段话）"),
    PromptVariable("已有项目", "known_projects", "known_projects", "上一轮已经存在的项目：id + 名称 + 当时基于的资源"),
    PromptVariable("问题", "problems", "problems", "本项目本轮生成的问题（未知盲区 / 已知缺陷）"),
    PromptVariable("价值", "value_opportunities", "value_opportunities", "本项目本轮生成的价值（全新方案 / 增量方案）"),
    PromptVariable("需求", "capability_voids", "capability_voids", "本项目本轮生成的需求：现有功能覆盖不了的能力缺口"),
    PromptVariable("固定主题", "fixed_themes", "fixed_themes", "Host 给定的固定主题：优化·推进·收益·探针·破局"),
    PromptVariable("上轮主题产出", "previous_theme_yield", "previous_theme_yield", "上一轮各主题各产出了多少任务，用来决定推导主题换不换"),
    PromptVariable("主题", "theme", "theme", "当前这一次要问的主题"),
    PromptVariable("主题类型", "theme_kind", "theme_kind", "这个主题是固定主题还是推导主题"),
    PromptVariable("主题说明", "theme_instruction", "theme_instruction", "这个主题具体要问什么"),
    PromptVariable("未结任务", "open_tasks", "open_tasks", "本项目还没结束的任务，用来避免重复提同一件事"),
    PromptVariable("历史任务", "all_tasks_history", "all_tasks_history", "本项目的全部历史任务"),
    PromptVariable("待审任务", "task_under_review", "task_under_review", "正在审的那一条任务（第六步逐条审核）"),
    PromptVariable("待审任务组", "tasks_under_review", "tasks_under_review", "正在整组审的任务（第六步成组审核）"),
    PromptVariable("待复核任务", "tasks_to_recheck", "tasks_to_recheck", "需要重新核对是否仍然成立的既有任务"),
    PromptVariable("已接受任务", "accepted_tasks_so_far", "accepted_tasks_so_far", "本轮已经通过审核的任务"),
    PromptVariable("已拒绝任务", "rejected_tasks_so_far", "rejected_tasks_so_far", "本轮被拒绝的任务与原因"),
    PromptVariable("新角度", "new_angles", "new_angles", "任务数量不足时补出来的思考角度（第七步当作新主题）"),
    PromptVariable("任务结果", "task_outcomes", "task_outcomes", "已经执行过的任务留下的结果"),
    PromptVariable("现实", "reality", "reality", "当前现实对象：reality_id + facts（六步流程里由 Host 直接拼出）"),
    PromptVariable("字段问题", "field_issues", "field_issues", "审核指出的、需要改写的字段问题"),
    PromptVariable("当前步骤", "step", "step", "发现阶段标记", note="旧链条"),
    PromptVariable("发现", "findings", "findings", "发现记录", note="旧链条"),
    PromptVariable("任务想法", "task_ideas", "task_ideas", "任务想法", note="旧链条"),
    PromptVariable("证据", "evidence", "evidence", "构建现实用的证据", note="旧链条"),
    PromptVariable("外部影响", "external_effects", "external_effects", "外部世界发生的影响", note="旧链条"),
    PromptVariable("执行变化", "execution_deltas", "execution_deltas", "执行带来的变化", note="旧链条"),
    PromptVariable("相关历史", "related_history", "related_history", "相关历史记录", note="旧链条"),
)

_BY_NAME: dict[str, PromptVariable] = {}
for _variable in VARIABLES:
    for _name in (_variable.name, _variable.alias):
        if _name in _BY_NAME:
            raise RuntimeError(f"prompt_template.VARIABLES 变量名重复：{_name}")
        _BY_NAME[_name] = _variable

for _reserved in INPUT_NAMES + CONTRACT_NAMES + ROLE_NAMES:
    if _reserved in _BY_NAME:
        raise RuntimeError(f"prompt_template 特殊变量名与普通变量重名：{_reserved}")


def variable_names() -> tuple[str, ...]:
    """所有可用变量名（中文名 + 英文别名 + 三个特殊变量）。"""

    return tuple(_BY_NAME) + INPUT_NAMES + CONTRACT_NAMES + ROLE_NAMES


@dataclass(frozen=True)
class RenderedPrompt:
    text: str
    used_input: bool
    used_contract: bool
    used: tuple[str, ...]


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, indent=2)


def has_placeholder(prompt_text: str) -> bool:
    return PLACEHOLDER.search(prompt_text) is not None


def render_prompt(
    prompt_text: str,
    *,
    role_key: str,
    payload: dict[str, Any],
    contract_text: str = "",
) -> RenderedPrompt:
    """把 `{{变量名}}` 换成本轮输入里的值。

    `payload` 必须是已经能 JSON 序列化的本轮输入（键就是模型看到的那些名字）。
    """

    # 先校验模板本身：写坏的 {{...}} 要在替换之前抓出来。
    # 校验只看模板，**不看替换结果**——本轮数据里完全可以合法地出现 {{ 或 }}
    # （LaTeX 的 $\text{Score}_{\text{ETF}}$、内联 JSON 片段等），那不是模板错误。
    if "{{{" in prompt_text or "}}}" in prompt_text:
        raise PromptTemplateError(
            f"提示词 '{role_key}' 里有三层以上的大括号：变量只能写成 {{{{变量名}}}}。"
        )
    residue = PLACEHOLDER.sub("", prompt_text)
    if "{{" in residue or "}}" in residue:
        raise PromptTemplateError(
            f"提示词 '{role_key}' 里有没写全的 {{{{...}}}}：变量名必须完整，不能嵌套、不能换行。"
        )

    used: list[str] = []
    used_input = False
    used_contract = False
    missing: list[str] = []
    unknown: list[str] = []

    def substitute(match: re.Match[str]) -> str:
        nonlocal used_input, used_contract
        raw = match.group(1).strip()
        if raw in INPUT_NAMES:
            used_input = True
            used.append(raw)
            return _as_text(payload)
        if raw in CONTRACT_NAMES:
            used_contract = True
            used.append(raw)
            return contract_text.strip()
        if raw in ROLE_NAMES:
            used.append(raw)
            return role_key
        variable = _BY_NAME.get(raw)
        if variable is None:
            unknown.append(raw)
            return match.group(0)
        if variable.key not in payload:
            missing.append(raw)
            return match.group(0)
        used_input = True
        used.append(raw)
        return _as_text(payload[variable.key])

    text = PLACEHOLDER.sub(substitute, prompt_text)

    if unknown:
        raise PromptTemplateError(
            f"提示词 '{role_key}' 用了不存在的变量：{'、'.join(sorted(set(unknown)))}。"
            f" 可用变量见 config/prompts/{role_key}.md 开头的 --- 说明块。"
        )
    if missing:
        available = sorted(
            {variable.name for variable in VARIABLES if variable.key in payload}
        )
        raise PromptTemplateError(
            f"提示词 '{role_key}' 用了本轮没有的变量：{'、'.join(sorted(set(missing)))}。"
            f" 这个角色本轮只有：{'、'.join(available) or '（无）'}。"
        )
    return RenderedPrompt(
        text=text,
        used_input=used_input,
        used_contract=used_contract,
        used=tuple(used),
    )


@dataclass(frozen=True)
class BuiltPrompt:
    """拼好的提示词，以及 Host 还要不要另外追加【本轮输入】。"""

    text: str
    include_input: bool
    source: str


def build_role_prompt(entry: Any, *, role_key: str, payload: dict[str, Any]) -> BuiltPrompt:
    """把一个角色的提示词（内置或用户自己的）与本轮输入拼起来。

    `entry` 来自 `PromptRegistry.template()`：有 `text` / `contract_text` /
    `append_input` / `source`。模板里没有 `{{...}}` 时，行为与从前完全一样。
    """

    text = str(entry.text)
    contract_text = str(getattr(entry, "contract_text", "") or "")
    mode = str(getattr(entry, "append_input", "auto") or "auto")
    used_input = False
    used_contract = False

    if has_placeholder(text):
        rendered = render_prompt(
            text,
            role_key=role_key,
            payload=payload,
            contract_text=contract_text,
        )
        text = rendered.text
        used_input = rendered.used_input
        used_contract = rendered.used_contract

    if contract_text.strip() and not used_contract:
        text = text.rstrip() + "\n\n" + contract_text

    if mode == "always":
        include_input = True
    elif mode == "never":
        include_input = False
    else:  # auto：模板自己放了输入就不再追加第二份
        include_input = not used_input

    return BuiltPrompt(
        text=text,
        include_input=include_input,
        source=str(getattr(entry, "source", "")),
    )
