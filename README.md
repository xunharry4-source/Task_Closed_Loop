# Task Closed-Loop Python

当前发布版本：**V1.3｜Implementation Hardening**  
冻结架构版本：**Architecture Contract V1.2 / Architecture Locked**

V1.3 **没有修改 7 Stage 总架构**。本次只修接口实现、CLI 适配和边界验证；以后普通功能修复继续遵守“**改 implementation，不改 Pipeline**”。

## 固定生产流程

```text
Stage 1  检查 CLI Project
         missing -> Host 复制 cli_project_template/
         valid   -> 直接复用
         invalid -> READY CLI 在原目录 repair
            ↓
Stage 2  资源与功能分析
         local_resources / remote_resources / functions
         CLI 直接在 cli_project/ 内持续生成、维护扫描/调用代码
         Host 执行这些代码并验证 Evidence / Provenance
         -> resources.generated.yml
         -> capabilities.generated.yml
            ↓
Stage 3  生成未审查任务（第一步，链条见下节）
         本项目资源 + 全局功能
           -> 问题 / 价值 / 需求 / 主题（四路独立，各一次调用）
           -> 每个主题各一次调用 -> 候选任务（必须挂在某条问题/价值/需求上）
            ↓
Stage 4  Audit CLI/API 独立审查任务是否合理
            ↓
Stage 5  只统计通过审查的业务 Task；检查是否过少
         enough -> 完成
         too few
            ↓
Stage 6  Task CLI/API 生成 Task Dimensions
            ↓
Stage 7  根据 Dimensions 重新生成 Task
            ↓
         所有新 Task 回到 Stage 4 审查
```

Stage 1–2 没完成时，Stage 3 不得开始。Capability Build / Execute 属于审查通过后的执行闭环，不得插入这 7 Stage 改变任务生产顺序。

配置了多个项目时，**每个项目各跑一次完整的 Stage 1–7**；Stage 2 的真实扫描全程只执行一次，
按项目切分后分发，产物写在 `generated/<project_id>/`。

## 生成任务的第一步：项目 → 问题/价值/需求 → 任务

```text
资源(按项目) + 功能(全局)
        ↓
   项目(实体)  ← 唯一隔离边界：资源分项目，功能所有项目共用
        ├── 问题发现   未知盲区 / 已知缺陷
        ├── 价值发现   全新方案 / 增量方案
        ├── 需求发现   突破型 / 基线型（现有功能覆盖不了的能力缺口）
        └── 主题规划   优化·推进·收益·探针·破局（固定）+ 2–5 个推导主题
                ↓
        每个主题各一次独立调用 → 任务
```

四路发现互不读对方的结论；只有"按主题生成任务"那一步同时看到三个中间层，因为任务要从里面挑来源。

任务只有三个基准：**资源、功能、主题**。提示词里不附加其它限制——可行性、价值大小、是否"合理"
都不在生成期判断（"不考虑"清单由 Host 在生成后过滤）。第一遍以**数量与覆盖面**为目标，
不做自我筛选，但**不得编造**依据。

**功能只给名称**（`codex_cli`、`gmail`…），不给简介、不给操作清单与 schema——模型本就认识这些工具，
写死操作清单只会让它以为功能只有那几项。任务写 `needed_functions`，Host 再映射回真实 capability id 交给 Stage 4。

**资源只给简介**：`resource_id` + 配置里的那句话 + 本项目的切分说明。Stage 2 的完整分析只进两处：
现实构建（每项目一次，`facts` 写成"现在有什么、到什么程度"）与 Stage 4 审查。
提示词因此压到约 1000 字符/次。
每条任务必须带 `entity_id` 与来源记录（问题/价值/需求），否则在生成期即被丢弃并记录原因。
提任务时**不按可行性预筛**：缺能力照样提，缺口写成需求，是否成立由 Stage 4 独立判断。

需要填的配置：

- `config/projects.yml`：项目清单（id 与任务库 `entities.entity_id` 一致）
- `config/preflight_sources.yml`：资源目录与功能。**归属不用填**——每份资源属于哪个项目由系统
  对照项目说明自动判断（可同时属于多个项目），结果缓存在 `cli_project/state/project_assignment.yml`；
  想钉住某一份时再写 `entities` 覆盖
- `config/task_store.yml`：任务库位置（项目、问题、价值、需求、主题、任务的长期记忆）

切回旧链条：`task_generation.first_step.mode: legacy_discovery`。

## 运行留痕

```text
log/<YYYY-MM>/<flow_id>/prompts/            每次模型调用的完整提示词与原始回复
log/<YYYY-MM>/<flow_id>/project_<id>.json   每个项目的链条全貌与入库统计
cli_project/generated[/<项目>]/rejections.round_N.yml   每轮各层被丢弃的原因
cli_project/generated[/<项目>]/tasks.*.yml  原有任务产物
任务库（默认参谋 SQLite）                    项目/问题/价值/需求/主题/任务 + 来源回写
```

提示词在调用**之前**写入；`PROMPT_CACHE_ENABLED=false` 可关闭。`log/` 已在 `.gitignore` 中。

长期业务语义保持不变：Task Discovery 基于 **Resource + Capability** 发现尚未利用的现实工作关系，**一份完整、当前、正常的数据仍然可能**产生分析、比较、验证、优化或机会发现 Task，**不是“没有异常所以没有 Task”**。Reality 是当前现实摘要，不是原始 Resources 的替代品。

## 架构冻结

```text
src/task_closed_loop/
├── pipeline/           # 冻结：7 Stage 顺序
├── contracts/          # 冻结：阶段接口/DTO
├── implementations/    # 普通功能修改主要发生在这里
├── preflight/          # Stage 2 扫描/调用/标准化底层
├── llm/                # CLI/API/模型底层
├── tasks/              # Task 领域能力
└── capability_runtime/ # CLI 与 Capability 执行底层
```

正式 Pipeline 只依赖 `contracts/`。`runtime.py` 只是 Composition Root，负责选择实现并注入 Pipeline。

普通修复默认只改：

- CLI Project：`implementations/cli_project/`
- 资源/Gmail/网盘/数据库/API 分析：`implementations/resource_analysis/` + `preflight/`
- Task 生成：`implementations/task_generation/` + Prompt
- Task 审查：`implementations/task_audit/`
- Task 数量策略：`implementations/task_count/`
- Task Dimensions：`implementations/task_dimensions/`
- 补充任务：`implementations/task_regeneration/`
- CLI 行为：`capability_runtime/cli/`

只有明确进行架构升级时才允许修改 `pipeline/`、核心 `contracts/` 和 `config/architecture_contract.yml`。

## Stage 1：CLI Project

默认长期工作目录：

```text
<task-closed-loop>/cli_project/
```

固定行为：

- 不存在：Host 复制 `cli_project_template/`；
- 已存在且结构正确：直接复用，不调用 CLI；
- 已存在但结构错误：调用真正 `READY` 的 CLI 在原目录修复；Host 只重新验证结构；
- 默认 CLI 失败时继续尝试下一个 `READY` CLI；用户显式指定 Engine 时不偷偷换 Engine。

CLI 状态区分：`MISSING / INSTALLED / NEEDS_AUTH / UNHEALTHY / READY`。`--version` 只能证明 CLI 已安装，不能证明可用；READY 还必须通过非交互认证/健康探测。

## Stage 2：真实资源与功能分析

正式配置位于 `config/preflight_sources.yml`，结构固定为：

```yaml
preflight_inputs:
  local_resources: []     # 必须写 entities（所属项目）
  remote_resources: []    # 必须写 entities
  functions: []           # 不分项目，不需要 entities
```

`entities` 只决定“哪个项目能看见这份资源”，不会进入 Stage 2 的分析输入，
因此不影响 Stage 2 的扫描行为与指纹（已生成的扫描代码不会因此重建）。

CLI 必须直接在长期 `cli_project/` 内生成和维护实际代码，例如：

```text
cli_project/analysis/main.py
cli_project/analysis/resources/
cli_project/analysis/functions/
cli_project/connectors/
```

Host 使用隔离 Python 执行入口，并显式加入 `analysis/` 与 `cli_project/` 两个允许的 module root，因此 CLI 可以正常生成多文件模块，而不是只能把全部逻辑塞进单个 `main.py`。

### Evidence / Truth Gate

Stage 2 不再接受“CLI 说这里有数据”作为事实。

- 本地目录：Host 自己重新扫描目录，生成文件数、目录数、相对文件树和 SHA-256 tree digest；CLI 自报的本地 evidence 不作为事实来源。
- Remote Resource / Function：必须返回结构化 Evidence，包含 `evidence_id / source_type / source_id / operation / status / observed_via`，以及 `raw_observation` 或位于 `cli_project/artifacts/preflight/` 的实际 artifact。
- 必须声明真实落地的 `implementation_files`，且文件必须位于 `cli_project/` 并实际存在。
- `availability_status` 必须显式为 `available / unavailable / failed`；最终标准 Resource/Capability 的 `availability` 必须与来源分析状态一致。
- 标准 Resource 必须通过 `metadata.source_input_ids` 关联 Stage 2 输入；标准 Capability 必须通过 `metadata.source_function_id` 关联 Function；Host 自动绑定 Evidence IDs。
- 没有 Evidence、只有文字总结、引用不存在的实现文件或 artifact、报告配置之外的 operation，都禁止进入 Stage 3。

Remote Evidence 是“真实执行留下的、Host 可检查的执行记录”，不是对互联网/第三方系统做密码学证明。对于高风险写操作，后续 Capability Runtime 仍需要独立 read-back / Host Verification。

标准输出固定为：

```text
cli_project/analysis/results/resources.analysis.yml
cli_project/analysis/results/functions.analysis.yml
cli_project/generated/resources.generated.yml
cli_project/generated/capabilities.generated.yml
```

## Stage 2 → Stage 3 边界

Stage 3 只读取标准化、已经物化的 Resource + Capability。原始路径、URI、连接参数和对象引用属于 Preflight 的 **Resource Reference**；Task Runtime 不接受未物化 Resource Reference。

Task Loader 会递归拒绝 Resource payload 和 Capability scope 中的原始定位/连接/凭据信息，例如：

```text
path / URI / URL / DSN / connection string / password / token / api_key / secret
```

但真实内容字段（如邮件正文）可以自然包含 URL 文本；这不会被误判为连接配置。

正式生产中，Stage 2 已经完成 Gmail/DB/Drive 等现实采集，所以 Stage 3 会关闭旧 TaskGenerationEngine 的 `Observation Acquisition` 触发，防止再次生成“先读取邮箱/数据库”的重复感知 Task。Task-only/lifecycle 测试仍保留原 Observation Acquisition 能力。

## Stage 3–7

- **Stage 3**：按第一步链条生成未审查 Task Candidate（每条带项目与来源血缘）；不 Audit，不生成 Dimensions。
- **Stage 4**：独立 Task Audit。
- **Stage 5**：只统计 Stage 4 通过的业务 Task；Observation Task 不能拿来凑数量。
- **Stage 6**：只有 Stage 5 判定任务过少才生成 Task Dimensions。
- **Stage 7**：每个 Dimension 作为一个推导主题重新提问（同一角度只问一次），
  来源仍限定在 Stage 3 已确认的问题/价值/需求；所有新 Candidate 强制回 Stage 4。
- 任务在整条流水线结束后写入任务库：同 `task_key` 只累加 `times_proposed`，
  被搁置且未到期的跳过，并回写来源记录 `status='已转任务'`。

## CLI 支持与 fallback

Capability Runtime 当前包含 Codex CLI、Gemini CLI、Claude CLI Adapter。

- Codex：使用登录状态探测，不把 `--version` 当 READY。
- Claude：使用 `claude auth status`；正常执行不使用 `--bare`，因此可沿用用户已登录的 Profile/OAuth。
- Gemini：使用极小 headless 请求验证当前凭据确实能服务请求。
- 默认模式按配置顺序选择 READY CLI；一个 READY CLI 在 Stage 1/2 实际执行失败时，可继续 fallback 到下一个 READY CLI。

安装、登录和账户授权仍由用户/环境预先完成；Task Closed Loop 不自动安装 CLI、不自动登录、不修改全局凭据。

## Secret

按项目固定要求，真实 Secret Value 只写入：

```text
cli_project/.env
```

**禁止**把 Password / Token / API Key 注入系统环境变量或子进程环境变量。配置文件只写 `secret_refs`。

Stage 2/Capability Runtime 由 Host 从 `.env` 读取声明过的 Secret，并通过结构化执行输入交给代码；不会把 Secret 设置进 `os.environ`。输出代码、Evidence、分析文件、标准 Resource/Capability 文件不得持久化 Secret Value。

因为 CLI 本身按架构直接工作在 `cli_project/`，`.env` 与 CLI 工作项目处于同一项目范围；V1.3 不虚假声称这里已经存在 OS 级文件隔离。若以后需要“CLI 连 `.env` 文件都不能读”，那属于单独的真实 Sandbox/权限架构升级。

## Task 生产后的执行闭环

```text
Accepted Task
→ Existing Capability?
→ 缺能力时 CLI 在 cli_project/ 创建/扩展能力代码
→ Test / Promote / Registry
→ Execute
→ Host Verification / read-back
→ TaskOutcomeRecord
→ 后续 Reality / Proliferation
```

CLI 自己输出 `success/done` 不等于执行正确；可信结果由 Host Verification 决定。

## 模型 / CLI 支持

Task/Audit LLM 适配仍保留：`gemini / gemma / ollama / lmstudio / openai / deepseek`，并保留 `codex_cli / gemini_cli / claude_cli` CLI 路径。Stage 3/6/7 使用 Task Profile，Stage 4 使用独立 Audit Profile。

## 本地 Task-only 测试

可以跳过 Stage 1–2，直接读取人工标准输入。入口配置仍为 `config/task_inputs.yml`：

```text
config/task_layer_test/resources.yml
config/task_layer_test/capabilities.yml
```

这是测试入口，不是正式生产旁路。

## 启动与测试

```bash
pip install -r requirements.txt
pip install -r requirements-dev.txt
python start.py
```

全量回归：

```bash
PYTHONPATH=src pytest -q -p no:cacheprovider
```

项目只维护两份人工说明文档：`README.md` 与 `ARCHITECTURE.md`。Prompt `.md` 属于 Runtime 资产，不计入人工文档。
