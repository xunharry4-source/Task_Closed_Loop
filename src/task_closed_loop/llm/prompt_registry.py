from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import yaml

from task_closed_loop.llm.prompt_template import has_placeholder

# 提示词：一个角色一个 YAML 文件，文件名就是角色名。
PROMPT_DIR = "config/prompts"
PROMPT_SUFFIX = ".yml"
# 这个目录里允许存在的非提示词文件：给人看的说明，不是角色
RESERVED_FILES = ("README.md", "readme.md", "说明.md")

# 文件里的键分两组：
#   给用户看的——系统完全不读，随便写多少说明
#   给系统用的——系统只读这两个
USER_KEYS = ("说明", "purpose", "变量", "variables", "备注", "notes")
PROMPT_KEYS = ("提示词", "prompt")
OPTION_KEYS = ("设置", "options")
ROLE_KEYS = ("角色", "role")
ALLOWED_KEYS = USER_KEYS + PROMPT_KEYS + OPTION_KEYS + ROLE_KEYS

APPEND_AUTO = "auto"
APPEND_ALWAYS = "always"
APPEND_NEVER = "never"
_APPEND_MODES = (APPEND_AUTO, APPEND_ALWAYS, APPEND_NEVER)
_ALLOWED_OPTIONS = ("append_input", "includes")


class PromptConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class PromptTemplateEntry:
    """一个角色的提示词正文，以及它要怎么拼。"""

    name: str
    text: str                 # 提示词正文（文件里 `提示词:` 那一段）
    contract_text: str        # manifest 里 includes 的共享段（引用语法）
    append_input: str         # auto / always / never
    source: str               # 文件路径，便于排错

    @property
    def full_text(self) -> str:
        if not self.contract_text.strip():
            return self.text
        return self.text.rstrip() + "\n\n" + self.contract_text


def _pick(data: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in data:
            return data[key]
    return None


def load_prompt_file(path: Path) -> tuple[str, dict[str, Any]]:
    """读一个提示词文件，返回 `(提示词正文, 设置)`。

    文件是 YAML。系统只读 `提示词`（正文）与 `设置`（两个开关）；
    `说明` / `变量` 这些是写给人看的，系统一律不读。
    """

    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise PromptConfigurationError(f"{path} 不是合法 YAML：{exc}") from exc
    if not isinstance(data, dict):
        raise PromptConfigurationError(
            f"{path} 必须是 YAML 映射，至少要有 `提示词:`（提示词正文）。"
        )

    unknown = sorted(set(data) - set(ALLOWED_KEYS))
    if unknown:
        raise PromptConfigurationError(
            f"{path} 里有不认识的键：{'、'.join(unknown)}；"
            f" 可写的是 {'、'.join(ALLOWED_KEYS)}。"
        )

    raw_prompt = _pick(data, PROMPT_KEYS)
    if raw_prompt is None or not str(raw_prompt).strip():
        raise PromptConfigurationError(
            f"{path} 缺少提示词正文：请写 `提示词: |` 再把正文缩进写在下面。"
        )
    if not isinstance(raw_prompt, str):
        raise PromptConfigurationError(
            f"{path} 的 `提示词` 必须是一段文本（用 `提示词: |` 写多行）。"
        )

    options: dict[str, Any] = {"append_input": APPEND_AUTO, "includes": True}
    raw_options = _pick(data, OPTION_KEYS) or {}
    if not isinstance(raw_options, dict):
        raise PromptConfigurationError(
            f"{path} 的 `设置` 必须是映射，只能写 {'、'.join(_ALLOWED_OPTIONS)}。"
        )
    unknown_options = sorted(set(raw_options) - set(_ALLOWED_OPTIONS))
    if unknown_options:
        raise PromptConfigurationError(
            f"{path} 的 `设置` 里有不认识的键：{'、'.join(unknown_options)}；"
            f" 只能写 {'、'.join(_ALLOWED_OPTIONS)}。"
        )
    if "append_input" in raw_options:
        mode = str(raw_options["append_input"]).strip().lower()
        if mode not in _APPEND_MODES:
            raise PromptConfigurationError(
                f"{path} 的 append_input 必须是 {'/'.join(_APPEND_MODES)} 之一，收到 {mode!r}。"
            )
        options["append_input"] = mode
    if "includes" in raw_options:
        value = raw_options["includes"]
        if not isinstance(value, bool):
            raise PromptConfigurationError(
                f"{path} 的 includes 必须是 true / false，收到 {value!r}。"
            )
        options["includes"] = value
    return raw_prompt, options


class PromptRegistry:
    """提示词：一个角色一个 YAML 文件，正文在 `config/prompts/` 里直接改。

    `src/task_closed_loop/prompts/manifest.yml` 只是索引：列出角色、它的 role 名与共享段
    （`includes`）。每个角色的文件是 `config/prompts/<角色名>.yml`：

        说明:    这个角色干什么（给人看，系统不读）
        变量:    这个角色能用哪些 `{{变量名}}`、各是什么意思（给人看，系统不读）
        设置:    append_input / includes 两个开关
        提示词:  真正发给模型的正文——变量写在哪里，它就替换在哪里

    变量名由系统固定提供（`llm/prompt_template.py` 的 `VARIABLES`），用户只是使用它们：
    把 `{{变量名}}` 放到正文的任何位置，替换就发生在那个位置。
    """

    def __init__(
        self,
        project_root: str | Path,
        manifest_path: str | Path,
        prompt_dir: str | Path | None = None,
    ):
        self.project_root = Path(project_root)
        manifest = Path(manifest_path)
        if not manifest.is_absolute():
            manifest = self.project_root / manifest

        with manifest.open("r", encoding="utf-8") as f:
            self._manifest = yaml.safe_load(f) or {}

        self._manifest_path = manifest
        self._fallback_dir = manifest.parent
        self._prompt_dir = self._resolve_dir(prompt_dir)
        self._files = self._scan()

    # -- 文件 ---------------------------------------------------------------

    def _resolve_dir(self, prompt_dir: str | Path | None) -> Path:
        path = Path(prompt_dir or PROMPT_DIR)
        if not path.is_absolute():
            path = self.project_root / path
        return path

    def _scan(self) -> dict[str, Path]:
        if not self._prompt_dir.is_dir():
            return {}
        known = set(self._manifest.get("prompts", {}))
        stray_markdown = sorted(
            path.name
            for path in self._prompt_dir.glob("*.md")
            if path.name not in RESERVED_FILES
        )
        if stray_markdown:
            raise PromptConfigurationError(
                f"{self._prompt_dir} 里的提示词必须是 YAML（{PROMPT_SUFFIX}）："
                f" 请把 {'、'.join(stray_markdown)} 改成 <角色名>{PROMPT_SUFFIX}。"
            )
        found: dict[str, Path] = {}
        for path in sorted(self._prompt_dir.glob(f"*{PROMPT_SUFFIX}")):
            name = path.stem
            if name not in known:
                raise PromptConfigurationError(
                    f"{path} 的文件名不是已知角色名。一个角色一个文件，文件名必须是："
                    + "、".join(sorted(known))
                )
            found[name] = path
        return found

    # -- 读取 ---------------------------------------------------------------

    def names(self) -> tuple[str, ...]:
        return tuple(self._manifest.get("prompts", {}).keys())

    def overridden(self) -> tuple[str, ...]:
        """哪些角色的提示词来自 `config/prompts/`（排错与日志用）。"""

        return tuple(sorted(self._files))

    def prompt_path(self, name: str) -> Path:
        """这个角色的提示词文件该放在哪（不管文件在不在）。"""

        return self._prompt_dir / f"{name}{PROMPT_SUFFIX}"

    def _builtin_entry(self, name: str) -> dict[str, Any]:
        try:
            return self._manifest["prompts"][name]
        except KeyError as exc:
            raise PromptConfigurationError(
                f"提示词 manifest 里没有角色 '{name}'。"
            ) from exc

    def _resolve_path(self, name: str) -> Path:
        entry = self._builtin_entry(name)
        path = self._files.get(name)
        if path is not None:
            return path
        fallback = self._fallback_dir / entry["file"]
        if fallback.is_file():
            return fallback
        raise PromptConfigurationError(
            f"角色 '{name}' 没有提示词文件：应该在 {self.prompt_path(name)}。"
        )

    def _contract_text(self, name: str) -> str:
        """manifest 里 includes 的共享段（目前就是引用语法）。"""

        entry = self._builtin_entry(name)
        parts: list[str] = []
        for include in entry.get("includes") or ():
            included = self._builtin_entry(include)
            if included.get("includes"):
                raise PromptConfigurationError(
                    f"Prompt include {include} must not include other prompts."
                )
            text, _ = load_prompt_file(self._resolve_path(include))
            parts.append(text)
        return "\n\n".join(parts)

    def template(self, name: str) -> PromptTemplateEntry:
        contract_text = self._contract_text(name)
        path = self._resolve_path(name)
        text, options = load_prompt_file(path)
        if not options["includes"]:
            contract_text = ""
        return PromptTemplateEntry(
            name=name,
            text=text,
            contract_text=contract_text,
            append_input=str(options["append_input"]),
            source=str(path),
        )

    def get(self, name: str) -> str:
        """提示词全文（正文 + 共享段）。没有本轮输入、因此不做变量替换的调用方走这里。

        Stage 2 的提示词就走这条路：它整段交给 CLI，没有"本轮输入"可取，
        所以这里不支持 `{{变量名}}`——写了就报错，不会把字面量当正文发出去。
        """

        text = self.template(name).full_text
        if has_placeholder(text):
            raise PromptConfigurationError(
                f"提示词 '{name}' 里写了 {{{{变量名}}}}，但这个角色没有本轮输入可取："
                " 它整段交给 CLI，变量替换只在第四~六步的模型调用里生效。"
            )
        return text

    def role(self, name: str) -> str:
        return str(self._builtin_entry(name)["role"])
