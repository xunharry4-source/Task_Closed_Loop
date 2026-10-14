# Task Closed-Loop Architecture

当前发布版本：**V1.3｜Implementation Hardening**  
冻结架构版本：**Architecture Contract V1.2 / Architecture Locked**

V1.3 不改变冻结架构，只修复实现层。7 Stage、Stage Contract、Pipeline 依赖方向保持 V1.2 不变。

## 1. 不可漂移的架构边界

```text
pipeline/
    ↓ only depends on
contracts/
    ↑ implemented by
implementations/
    ↑ uses
preflight / llm / tasks / capability_runtime / other domain modules
```

三层职责：

1. `pipeline/production.py`：只定义 7 Stage 调用顺序与 Stage 7 → Stage 4 回边；
2. `contracts/`：定义各阶段输入/输出 DTO 与 Protocol；
3. `implementations/`：承载可替换业务实现。

机器架构锁：`config/architecture_contract.yml`，当前仍为 **1.2**。发布版本升级到 V1.3 不代表架构版本变化。

除非用户明确要求“改变系统架构”，普通修复不得通过改 Stage 顺序、在 Pipeline 中 import concrete implementation 或新增正式旁路来解决。长期规则是：**改接口的实现，不改 Pipeline**。

## 2. 固定接口

| Stage | Contract | 默认实现 |
|---|---|---|
| 1 | `CliProjectManager` | `implementations/cli_project/` |
| 2 | `ResourceCapabilityAnalyzer` | `implementations/resource_analysis/` |
| 3 | `InitialTaskGenerator` | `implementations/task_generation/` |
| 4 | `TaskAuditor` | `implementations/task_audit/` |
| 5 | `TaskCountPolicy` | `implementations/task_count/` |
| 6 | `TaskDimensionGenerator` | `implementations/task_dimensions/` |
| 7 | `TaskRegenerator` | `implementations/task_regeneration/` |

## 3. 唯一正式生产图

```text
Stage 1 | CLI Project Check
  missing -> Host copy template
  valid   -> reuse
  invalid -> READY CLI repair in place
       ↓
Stage 2 | Resource + Function Analysis
  CLI cwd = cli_project/
  generate/maintain real scan + connector code
  Host executes code
  Evidence / Provenance / Task-boundary validation
  -> resources.generated.yml
  -> capabilities.generated.yml
       ↓
Stage 3 | Initial Task Generation（第一步，见 §7.1）
  本项目资源 + 全局功能
    -> 问题 / 价值 / 需求 / 主题（四路独立）
    -> 每个主题各一次 -> 未审查候选（必须带来源记录）
       ↓
Stage 4 | Independent Task Audit
       ↓
Stage 5 | Count accepted business Tasks
       ├─ enough -> finish
       └─ too few
              ↓
Stage 6 | Task Dimension Generation
              ↓
Stage 7 | Regenerate Tasks using Dimensions
              ↓
            Stage 4
```

任何 Stage 7 Candidate 必须重新经过 Stage 4。

配置了多个项目时，**每个项目各跑一次完整的 Stage 1–7**（每个项目需要自己的 Reality，
而候选被硬绑定在单一 `reality_id` 上）。Stage 1 幂等复用，Stage 2 的真实扫描全程只执行一次
并按项目切分；产物写在 `generated/<project_id>/`（只有一个项目时仍写 `generated/`）。

## 4. Stage 1：Project Check / Repair

默认：`<project_root>/cli_project/`。

三条路径固定：

- `missing`：Host 复制 `cli_project_template/`；
- `valid`：直接复用；
- `invalid`：CLI `cwd=cli_project/` 原位 repair，Host 重新 verify。

Host 不允许在 `invalid` 分支通过偷偷复制模板掩盖结构错误。

### CLI 状态模型

```text
MISSING
INSTALLED
NEEDS_AUTH
UNHEALTHY
READY
```

`--version` 只负责 MISSING/INSTALLED/UNHEALTHY 的基础判断；只有额外 Auth/Health Probe 成功才是 READY。

默认 Engine 选择允许 fallback：首个 READY CLI 实际 repair/build 失败时，继续下一个 READY CLI。显式指定 Engine 时保持用户选择，不暗中切换。

## 5. Stage 2：现实采集，而不是 LLM 自报

输入：

```yaml
preflight_inputs:
  local_resources: []
  remote_resources: []
  functions: []
```

CLI 直接在长期项目内维护：

```text
cli_project/analysis/main.py
cli_project/analysis/resources/
cli_project/analysis/functions/
cli_project/connectors/
```

Host 用 `python -I` 运行 Stage 2 入口，同时只把下列根加入模块路径：

```text
cli_project/analysis/
cli_project/
```

因此隔离模式下仍支持多文件 Python 项目，CLI 不需要把所有逻辑塞进 `main.py`。

### 5.1 Local Resource Truth

CLI 负责内容理解与分析代码，但“目录里实际有什么文件”由 Host 独立再扫描：

```text
relative file tree
file_count
directory_count
file sizes
SHA-256 tree digest
```

Host 生成 `host-local:*` Evidence。CLI 自报本地 Evidence 不具有事实权威。

### 5.2 Remote Resource / Function Evidence

Remote / Gmail / Drive / Database / API / Calendar 分析必须返回结构化 Evidence：

```text
evidence_id
source_type
source_id
operation
status
observed_via
raw_observation OR artifact_ref
```

并且必须有真实存在的 `implementation_files`。

Host 检查：

- Evidence 是结构化对象，不是“我已经查过”的字符串；
- Source ID / Source Type 与配置吻合；
- Operation 没超出配置允许范围；
- Artifact 必须真实存在于 `cli_project/artifacts/preflight/`，并计算 SHA-256；
- Inline observation 计算 observation SHA-256；
- `available` Function 至少有一条 `success/verified_empty` Evidence；
- Analysis ID 不得重复；
- `availability_status` 必须显式给出。

这消除了“仅凭 CLI 文字结论就写入 Reality”的旧错误。由于 Remote 调用代码本身仍由 CLI 创建，这不是对第三方系统的密码学证明；高风险执行结果继续由执行层 read-back / Host Verification 处理。

### 5.3 Output Provenance

每个标准 Resource：

```text
metadata.source_input_ids
metadata.stage2_evidence_ids
```

每个标准 Capability：

```text
metadata.source_function_id
metadata.stage2_evidence_ids
```

`Resource/Capability.availability` 必须与其 Stage 2 来源分析状态一致，禁止 Evidence 显示 failed/unavailable 而标准输出伪装 available。

输出：

```text
cli_project/analysis/results/resources.analysis.yml
cli_project/analysis/results/functions.analysis.yml
cli_project/generated/resources.generated.yml
cli_project/generated/capabilities.generated.yml
```

## 6. Stage 2 → Task Layer 安全边界

Task Runtime 不负责连接外部系统，因此标准 Resource/Capability 不能重新携带 Preflight Transport 信息。原始路径、URI、对象定位与连接材料属于 Preflight 的 **Resource Reference**；**Task Runtime 不接受**未物化 Resource Reference。

Resource payload 递归拒绝结构化：

```text
path / root / uri / url / dsn / connection / connection_string
credentials / password / token / api_key / secret / access_token / refresh_token
client_secret / private_key
```

Capability `target_scope` 同样递归拒绝原始 locator/connection material。

自然内容字段（邮件正文、文本、summary 等）可以提到 URL；验证器区分“内容中的 URL”与“用于连接的 URL 字段”。

## 7. Task Discovery 与既有闭环语义

Task Discovery 的长期定义没有改变：**Resource + Capability** 是发现 Task 的基础，但不要求 Resource 先出现异常。**一份完整、当前、正常的数据仍然可能**存在值得执行的分析、比较、验证、优化或机会发现工作；核心**不是“没有异常所以没有 Task”**。Reality 是当前现实摘要，不是原始 Resources 的替代品。

V1.3 同样保留既有 Task 闭环契约：

- `Observation Acquisition`（Task-only / lifecycle 场景）；
- `Outcome Normalization Gate`；
- Outcome `subject_refs`；
- Task `identity_anchor_refs`；
- `consumed_outcome_ids` Outcome Receipt；
- `supersedes_outcome_ids`；
- 多 Parent / 多 Outcome / 多代 Task Proliferation；
- 大 Outcome `discovery_payload` / bounded discovery context。

## 7.1 Stage 3 第一步：项目 → 问题/价值/需求 → 任务

生成任务的第一步按参谋 SKILL 的链条执行（`task_generation.first_step.mode: skill_chain`，默认）。
Stage 4 审查、Stage 5 数量检查、Stage 6 维度生成与全部产物保存**完全不变**；Stage 7 的顺序、
回边与 Contract 也不变，只是改为在同一条链上补充生成。Pipeline 与 Contract 本身没有改——
新链条只是 `InitialTaskGenerator` / `TaskRegenerator` 的另一种实现。

```text
资源(按项目) + 功能(全局)
        ↓
   项目(实体)  ← 唯一隔离边界
        ├── 问题发现     UNKNOWN_BLINDSPOT / KNOWN_DEFECT
        ├── 价值发现     NOVEL_PARADIGM / INCREMENTAL_SCHEME
        ├── 需求发现     BREAKTHROUGH_NEED / BASELINE_NEED
        └── 主题规划     5 固定 + 2–5 推导
                ↓
        每个主题各一次调用 → 任务（必须挂在上面某条记录上）
```

**隔离边界只有资源。** 资源按项目划分，功能不分项目：所有项目都可以使用全部已配置的功能。
因此 `entities` 归属只写在 `local_resources` / `remote_resources` 上，功能条目不需要。

- **项目层**：`config/projects.yml` 声明项目（id 与任务库 `entities.entity_id` 一致）。
  **归属由系统自己判断**：Stage 1/2 跑完后，用项目说明对照每份资源的简介判断它属于谁
  （`projects/assignment.py`，一次调用），一份资源可同时属于多个项目。结果按
  「项目 + 资源」指纹缓存在 `cli_project/state/project_assignment.yml`，没变就不再问。
  配置里的 `entities` 变成可选覆盖：写了就钉住，并且不会再去问模型。
  归属不进 Stage 2 payload，因此不影响 Stage 2 指纹与已生成的扫描代码。
- **项目隔离**：`projects/grouping.py` 从 Stage 2 标准输出的 `metadata.source_input_ids`
  还原资源归属再切分（`ResourceSnapshot` 没有 metadata 字段，归属在 Stage 2→3 边界会丢，
  所以从标准文件读回）。候选与任务被硬绑定在单一 `reality_id` 上，所以**每个项目各跑一次
  完整流水线**；Stage 2 由 `ProjectStage2Cache` 共享，真实扫描全程只执行一次。
- **四路独立发现**：问题、价值、需求、主题各一次调用，输入都只是
  `project` + 本项目资源 + 现实 + 全局功能，**互不读对方的结论**——否则一层的盲区会变成
  下一层的起点。只有"按主题生成任务"那一步会同时看到三个中间层，因为任务要从里面挑来源。
- **主题**：5 个固定主题（优化/推进/收益/探针/破局）由 Host 给定，探针与破局不可省略
  （模型要求跳过时记录并照常提问）；推导主题 2–5 个，按上周 `yield_count` 轮换。
  每个主题一次独立调用，互不污染上下文。
- **任务只有三个基准**：资源、功能、主题。提示词里不再附加别的限制——
  可行性、价值大小、是否"合理"都不在生成期判断。用户的"不考虑"清单（`exclusions`）
  由 Host 在生成之后过滤，不写进提示词。
- **生成任务时带项目说明**：该步输入的 `project` 含项目 id、名称、说明，以及
  `data_source_slices`（这个项目在各数据源里只用哪一部分），任务必须是这个项目的工作。
- **功能只给名称**：第一步的输入里功能就是一串名称（`codex_cli`、`gmail`…），
  不给简介、不给操作清单、不给 `target_scope` / `input_schema`。模型对这些工具本来就有
  完整认知，必要时还会自己去查；把 Stage 2 探到的操作清单塞进去，只会让它以为这个功能
  就只有那几个操作。任务写 `needed_functions`（功能名称），Host 再映射回 Stage 2 实际
  报告的 capability id 交给 Stage 4，因此审查侧的能力判断照旧。
- **资源只给简介**：第一步看到的是「`resource_id` + 你在配置里写的那句话 + 本项目的切分说明」。
  Stage 2 的完整分析（141 KB 级）只进两处：一次是**现实构建**（每项目一次调用，
  `facts` 写成"现在有什么、到什么程度"的简要清单），一次是 **Stage 4 审查**。
  四路发现与按主题生成都只看简介 + 这份现实，因此引用资源时写 `resource:<id>`，
  要指具体内容就引 `reality:current#...`。
- **血缘**：候选必须带 `source_kind` + `source_ref_id` 指向本项目本轮的真实中间层记录；
  没有来源的候选由 Host 丢弃并记录原因。层级与类型（TIER_1/TIER_2、UNKNOWN_PROBE /
  NEW_PARADIGM / FIX_AUDIT / CREATIVE_PROGRESS / DECISION_ANALYSIS /
  MECHANISM_ITERATION）由 Host 判定，不由模型填。
- **不按可行性预筛**：缺能力的任务照常提出，缺口写成需求；是否成立仍由 Stage 4 独立判断。
- **第一遍要多、要全**：四路发现与按主题生成都以数量和覆盖面为目标，不做自我筛选——
  "可能不合理 / 没意义 / 价值不大" 不是放弃的理由，筛选是 Stage 4 的职责。
  唯一不放松的是**不得编造**：每条记录与任务都必须有真实存在的依据引用。
- **Stage 7 也走主题链条**：Stage 6 的每个思考角度被当成一个推导主题，由
  `ProjectChainTaskRegenerator` 重新问一次（同一角度只问一次），来源仍限定在 Stage 3
  已确认的问题/价值/需求。否则补充轮的候选没有来源记录，任务库必须拒收。
- **持久化**：`config/task_store.yml` 指定任务库（默认参谋 SQLite 库）。项目、问题、价值、
  需求、主题在第一步写入；任务在整条流水线跑完后写入，并回写来源 `status='已转任务'`。
  `task_key = sha256(entity_id, task_type, core_target)`：同 key 的未结任务只
  `times_proposed+1`，被搁置且未到期的跳过，命中 `exclusions` 的候选在生成期即丢弃。
  **对已存在的任务库只写数据，绝不改结构**；缺表直接报错并指出表名。

旧链条（发现 → 任务想法 → 候选任务，单一全局 reality）保留在
`implementations/task_generation/llm.py`，用 `first_step.mode: legacy_discovery` 切回。

## 8. Stage 3：不重复 Stage 2 感知工作

旧 TaskGenerationEngine 支持 Observation Acquisition，这是 Task-only/lifecycle 模式的重要能力。

但冻结生产流程里 Stage 2 已经负责现实采集。因此正式 `InitialTaskGenerator` 在进入旧引擎前构造生产视图，把 `can_observe_state` 的 Task-generation trigger 关闭，同时不修改原始 Capability 对象。

因此：

```text
Stage 2 已读取 Gmail
≠ Stage 3 再生成“先读取 Gmail”的 Observation Task
```

Task-only / Outcome lifecycle 仍可保留原 Observation Acquisition 语义。

## 9. Stage 4–7

- Stage 4：独立 Audit，实现不得合并回 Stage 3。
- Stage 5：只统计审核通过的业务 Task。
- Stage 6：只有 Task 过少才产生 Dimensions。
- Stage 7：依据 Dimensions 补充生成；全部回 Stage 4。
  `skill_chain` 模式下，每个 Dimension 作为一个推导主题重新提问（同一角度只问一次），
  补充出来的任务与第一轮一样带项目与来源血缘。

旧 `Coverage Expansion` 不允许在 Stage 3 偷跑 Dimensions。

## 10. CLI Adapter 运行语义

### Codex CLI

先检查安装，再运行登录状态探测；只有认证可用才 READY。

### Claude CLI

使用 `claude auth status`。Build/Analyze 不使用 `--bare`，避免绕过用户已经登录的 Profile/OAuth。

### Gemini CLI

由于缺少等价的稳定 `auth status`，使用最小 headless、plan/sandbox 请求验证凭据是否真正能服务请求。

Task Closed Loop 不负责安装 CLI、登录账户或修改全局认证。

## 10.1 模型调用留痕

每次模型调用的**完整提示词**与**原始回复**都会落盘：

```text
log/<YYYY-MM>/<flow_id>/prompts/<时间戳>_<role>_<sha12>_<req>.json      提示词
log/<YYYY-MM>/<flow_id>/prompts/<时间戳>_<role>_response_<sha12>.json   回复
```

提示词在调用**之前**写入：挂死、被杀、CLI 自身报错的那一次，恰恰是最需要看提示词的。
全部 7 个适配器都记录（Gemini 家族在 `_create_interaction`，Ollama 家族在 `_chat_json`）。
提示词内嵌 Resource 内容，因此只落本地——`log/` 已在 `.gitignore` 中。
用 `PROMPT_CACHE_ENABLED=false` 关闭。

## 11. Secret Contract

用户固定要求：Secret 唯一持久化位置是：

```text
cli_project/.env
```

禁止把真实 Password / Token / API Key 写到系统环境变量或子进程 `env`。

配置和 Build Contract 使用 `secret_refs`。Host 只解析被声明的 key，并把值放入结构化执行输入；不会执行：

```python
os.environ["..."] = secret
```

CLI 本身工作在 `cli_project/`，因此 `.env` 文件在同一长期项目范围内；当前架构没有伪造“CLI 文件系统绝对看不到 `.env`”的保证。要增加这种保证必须引入真实 OS/Sandbox 权限层，并视为架构升级。

## 12. 执行闭环与结果可信度

7 Stage 只负责生产并审查 Task。Accepted Task 后才进入：

```text
Capability exists?
  yes -> execute
  no  -> CLI create/extend code -> test -> promote -> registry
                 ↓
              execute
                 ↓
        Host Verification / read-back
                 ↓
          TaskOutcomeRecord
```

进程退出码或 CLI 自己输出 `success` 只能表示 process completed；只有 Verification Contract 通过的结果才是 trusted Outcome。

## 13. Architecture / Implementation Regression

架构测试继续验证：

- Pipeline 只依赖 Contracts；
- 7 Stage 顺序固定；
- Stage 7 → Stage 4；
- Stage 1 三分支不混用；
- Stage 2 CLI `cwd=cli_project/`；
- Stage 3/4 是独立接口。

V1.3 新增破坏性实现测试，专门防止：

- Resource payload 嵌套 path/DSN/token 穿透 Task Boundary；
- CLI 无 Evidence 自报 Gmail/DB 数据被当事实；
- 多文件 Stage 2 import 在 `python -I` 下失败；
- Local Resource 使用 CLI 自报 evidence 代替 Host Scan；
- Output availability 与来源证据状态冲突；
- Stage 3 恢复重复 Observation Acquisition；
- CLI 只有 `--version` 成功就被误判 READY；
- 第一个 CLI 失败后不 fallback；
- Claude Adapter 重新引入 `--bare`。

项目仍只维护 `README.md` 与 `ARCHITECTURE.md` 两份人工说明文档。
