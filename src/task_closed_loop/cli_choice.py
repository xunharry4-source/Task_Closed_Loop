"""第一步配的那一个 CLI——一处决定，到处使用。

`preflight_inputs.cli` 同时决定第二步（分析并填模版）用哪个 CLI，以及第四~六步
（生成问题/价值/需求/主题/任务、审核任务）走哪个推理适配器。`.env` 里的
`TASK_LLM_ADAPTER` / `AUDIT_LLM_ADAPTER` 仍可单独覆盖。
"""

from __future__ import annotations

# 用户说的名字 -> 适配器名（按 CLI 可执行文件命名）
CLI_ALIASES: dict[str, str] = {
    "chatgpt": "codex_cli",
    "codex": "codex_cli",
    "gemini": "gemini_cli",
    "claude": "claude_cli",
}


def configured_cli_engine(config: dict) -> str:
    """`preflight_inputs.cli` 解析成适配器名；没配就返回空串。"""

    section = (config or {}).get("preflight_inputs") or {}
    raw = section.get("cli")
    if isinstance(raw, dict):  # 旧写法：cli.engine
        raw = raw.get("engine")
    name = str(raw or "").strip().lower()
    return CLI_ALIASES.get(name, name)
