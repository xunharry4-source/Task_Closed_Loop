# LLM 提示词清单 V0.7

当前项目中的 LLM Prompt 已按职责拆分。

## Reality

- `reality_builder.md`
  - 建立 Current Reality

## Existing Task Continuity

- `existing_task_continuity.md`
  - 判断 Existing Task 与 Current Reality 的连续关系

## Task Generation

- `task_discovery.md`
  - 从 Current Reality + Effective Existing Tasks + Capabilities 发现 Candidate

- `task_candidate_destructive_audit.md`
  - 对单个 Candidate 尝试破坏

- `task_candidate_set_audit.md`
  - 对 Candidate Set 尝试发现重复、碎片化与重叠

## Final Task Reality

- `task_reality_validity.md`
  - 对最终 Task 与 Current Reality 的关系做现实有效性审查

## Closed-Loop Runtime Context

- `runtime_prompt.md`
  - Task Reality Continuity 与 Task Generation 的总闭环上下文

## Runtime Output

- `output_template.md`

## Prompt Registry

统一入口：

```text
src/task_closed_loop/prompts/manifest.yml
```

正式 Runtime 由配置的 Ollama Adapter 调用这些 Prompt。


## Runtime Adapter

正式 Runtime 当前支持：

```text
gemini
ollama
```

Gemini 使用 Google Gen AI SDK Interactions API：

```python
client.interactions.create(...)
```

Ollama 使用本地 `/api/chat`。

两种 Adapter 都调用同一组 Prompt 与同一套 Python Task Pipeline。
