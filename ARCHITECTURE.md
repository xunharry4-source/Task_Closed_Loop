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
Stage 3 | Initial Task Generation
  Resource + Capability -> unreviewed candidates
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

旧 `Coverage Expansion` 不允许在 Stage 3 偷跑 Dimensions。

## 10. CLI Adapter 运行语义

### Codex CLI

先检查安装，再运行登录状态探测；只有认证可用才 READY。

### Claude CLI

使用 `claude auth status`。Build/Analyze 不使用 `--bare`，避免绕过用户已经登录的 Profile/OAuth。

### Gemini CLI

由于缺少等价的稳定 `auth status`，使用最小 headless、plan/sandbox 请求验证凭据是否真正能服务请求。

Task Closed Loop 不负责安装 CLI、登录账户或修改全局认证。

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
