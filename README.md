# Task Closed-Loop Python

## 本地运行

Windows：

```text
start.py
test.py
```

命令行：

```bash
python start.py
python test.py
```

直接使用本地已经安装好的 Python/依赖。


## 启动

```bash
pip install -r requirements.txt
python start.py
```


Python 版闭环任务系统骨架。

## V0.5 新增

- 真正实现 Task Generation Pipeline
- Resource 不再携带预制 `task_candidate`
- Task Discovery
- Candidate Destructive Audit
- Candidate Set Audit
- Deterministic Finalizer
- Finalizer Fidelity Audit
- Task Reality Validity Audit
- `任务生成机制.md`

- 真正实现 R1–R5 破坏式审查
- `审查机制.md`
- DiagnosticSnapshot / DiagnosticFinding / DiagnosticReport
- 五类独立 Reviewer + 汇总 Runner

- 项目架构.md
- 启动说明.md
- YAML 文件内字段级中文说明

- 正式依赖文件
- YAML 配置系统
- `config/default.yml`
- `config/runtime.yml`
- `config/providers.yml`
- `config/diagnostics.yml`
- YAML 配置加载与深层合并
- Provider Registry 由 YAML 装配
- 启动入口读取 YAML
- ZIP 清理 `__pycache__`

## 依赖

### 核心依赖

```bash
pip install -r requirements.txt
```

当前核心只有：

```text
PyYAML
```

因为 Runtime Core 使用 Python 标准库，YAML 是正式配置格式。

### 开发依赖

```bash
pip install -r requirements-dev.txt
```

### 可选真实 Provider / LLM 依赖

```bash
pip install -r requirements-optional.txt
```

也可以按 `pyproject.toml` extras 安装：

```bash
pip install -e ".[openai]"
pip install -e ".[google]"
pip install -e ".[http]"
pip install -e ".[dev]"
```

## YAML 配置

启动默认读取：

```text
config/default.yml
```

然后自动合并：

```text
config/runtime.yml
config/providers.yml
config/diagnostics.yml
```

### Provider 配置示例

```yaml
providers:
  mock:
    enabled: true
    adapter: task_closed_loop.adapters.mock:MockProvider
```

新增 Provider 时，Core 不需要改动，只需要：

1. 实现对应 Port。
2. 在 `providers.yml` 注册 Adapter。
3. 安装该 Provider 所需可选依赖。

## 运行

```bash
pip install -r requirements.txt
PYTHONPATH=src python -m task_closed_loop.app.runtime
```

## 测试

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

## 架构边界

- Resource / Capability = Ports
- External Systems = Adapters
- Provider Registry = YAML 装配
- Reality Engine 不读取 Existing Tasks
- Task Continuity 在 Current Reality 建立后运行
- R1–R5 留在 Offline Diagnostics

## 添加 Resource / Capability

详细说明：

```text
资源与能力扩展说明.md
开发扩展速查.md
```

其中包含 Fake 测试、真实 Adapter、YAML 注册、Secret、Existing Task、Effect 回流和测试示例。



## LLM 配置

正式 Runtime 必须显式配置 LLM。

当前支持 Gemini 与 Ollama。

```env
LLM_ADAPTER=ollama
LLM_MODEL=<ollama model>
```

正式 Runtime 中已经移除 FakeLLM / MockLLM。

使用真实 LLM 测 Resource / Capability：

```text
修改 config/test_resources.yml + config/test_capabilities.yml
运行 test_runtime.py
```

详细见 `测试Resource与Capability配置说明.md`。


## Gemini

Google Gen AI SDK：

```bash
pip install -U google-genai
```

配置示例：

```env
LLM_ADAPTER=gemini
LLM_MODEL=gemini-3.6-flash
GEMINI_API_KEY=<secret>
```

项目使用 `client.interactions.create(...)`。

详细见：

```text
Gemini配置与测试说明.md
```


## 最简单的本地 Prompt 测试

1. 配置 Gemini 或 Ollama。
2. 只修改：

```text
config/test_resources.yml + config/test_capabilities.yml
```

3. 运行：

```text
test_runtime.py
```

Resource / Capability 测试不需要修改 Python，也不需要 Scenario。

详细见：

```text
测试Resource与Capability配置说明.md
```


## Resource / Capability 的两个入口

### 本地测试

Resource：

```text
config/test_resources.yml
```

Capability：

```text
config/test_capabilities.yml
```

运行：

```text
test_runtime.py
```

### 真实外部系统

```text
config/mcp_servers.yml
```

MCP `resources` 自动成为 Resource，MCP `tools` 自动成为 Capability。


## Python 入口

正式运行：

```text
start.py
```

真实 LLM + 测试 Resource / Capability：

```text
test_runtime.py
```

自动回归：

```text
test.py
```

三个入口彼此独立，不通过运行参数切换。



## LM Studio

LLM Adapter：

```env
LLM_ADAPTER=lmstudio
LLM_MODEL=<LM Studio /v1/models 返回的模型 id>
LMSTUDIO_BASE_URL=http://127.0.0.1:1234/v1
```

详细见：

```text
LM Studio配置与测试说明.md
```
