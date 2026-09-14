# Stage 2｜固定 Resource / Function 分析

你正在 **真实、长期存在的 `cli_project/` 工作目录**中工作。不要创建第二个项目，不要使用项目外 staging，也不要把代码写到临时项目。

你的任务不是生成业务 Task。你的任务是：根据 Host 提供的三类固定输入，直接在当前 CLI Project 内创建/更新代码，真实读取资源与功能状态，并输出 Stage 2 固定结构。

## 固定输入类型

1. `local_resources`
   - Host 已检查目录存在；
   - 必须在 `analysis/resources/` 中生成/维护读取与分析代码；
   - 必须真实扫描目录结构、数据类型和内容；
   - Host 会独立重新扫描本地目录并生成可信文件树 Evidence，因此不得伪造文件数或结构。

2. `remote_resources`
   - 例如网盘目录、远端数据作用域；
   - 必须通过其 `function_id` 对应的真实调用代码查询；
   - 必须说明当前实际观察到的数据与内容；
   - 查询结果必须留下结构化 Evidence，不能只写自然语言结论。

3. `functions`
   - 例如 cloud drive、Gmail、database、API、calendar 等；
   - 必须在 `connectors/` / `analysis/functions/` 中生成或维护真实调用代码；
   - 必须实际验证哪些配置操作当前可用；
   - 能读取状态时，必须真实读取允许范围内的数据并说明当前有什么；
   - 不允许根据功能名猜能力。

## 固定代码位置

```text
analysis/main.py                 固定入口
analysis/resources/              本地/远端资源分析代码
analysis/functions/              功能分析与编排代码
connectors/                      Gmail/网盘/数据库/API 等实际调用代码
analysis/results/                Host 写入最终分析文件
artifacts/preflight/             可选原始 Evidence 文件
```

已有代码必须增量维护，禁止每轮推倒重建。

## 固定入口

`analysis/main.py` 必须提供：

```python
def run(inputs, context):
    ...
```

`context["secrets"]` 只包含当前 functions 通过 `secret_refs` 声明的 `.env` Key 对应值。禁止把 Secret 写回源码、日志、Evidence、分析结果或标准文件。

## 返回结构

四部分都必须存在：

```python
{
  "resource_analysis": [...],
  "function_analysis": [...],
  "resources": [...],
  "capabilities": [...]
}
```

### resource_analysis

每个配置的 local/remote resource 都必须有一条：

```yaml
input_id: configured-resource-id
availability_status: available | unavailable | failed
implementation_files:
  - analysis/resources/example.py
directory_structure: {...}
data_summary: {...}
content_summary: {...}
evidence: [...]
```

对于 local resource，Host 会用自己的文件树扫描 Evidence 覆盖/验证 CLI 自报 Evidence。

对于 remote resource，`evidence` 必须是结构化记录，每条至少包含：

```yaml
evidence_id: unique-id
source_type: remote_resource
source_id: configured-resource-id
operation: configured-operation
status: success | verified_empty | unavailable | failed
observed_via: generated_code
raw_observation: {...}          # 或 artifact_ref 二选一
# artifact_ref: artifacts/preflight/...   # 必须是真实存在的文件
```

### function_analysis

每个配置的 function 必须有一条：

```yaml
function_id: configured-function-id
availability_status: available | unavailable | failed
implementation_files:
  - connectors/example.py
available_operations: [...]
observed_data_summary: {...}
can_observe_state: true | false
observable_state: ...
target_scope: {...}
evidence:
  - evidence_id: unique-id
    source_type: function
    source_id: configured-function-id
    operation: configured-operation
    status: success | verified_empty | unavailable | failed
    observed_via: generated_code
    raw_observation: {...}      # 或 artifact_ref
```

`available` 不是默认值。只有真实调用/验证成功后才能写 `available`。无法认证、无权限、服务错误时必须明确 `unavailable` 或 `failed`。

### resources

这里只能输出已经物化的现实事实。每条必须显式写：

```yaml
id: ...
type: ...
source_identity: 稳定逻辑身份
availability: available | unavailable | failed
payload: ...
metadata:
  source_input_ids: [configured-resource-id]
```

禁止在 `payload`、`source_identity` 中输出原始路径、URI、DSN、host/port、connection string、password、token、credential、secret 等连接信息。Host 会递归拒绝这些泄漏。

### capabilities

每条必须显式写：

```yaml
id: ...
action_type: ...
availability: available | unavailable | failed
metadata:
  source_function_id: configured-function-id
```

必须明确真实功能语义、Scope、可用操作，以及是否能观察外部状态。Task 层不会根据名称猜测。Host 会把 Stage 2 Evidence ID 自动绑定到最终 Resource / Capability metadata。

## 硬约束

- 不生成 Task；
- 不修改固定项目架构；
- 不创建第二个项目；
- 所有代码直接留在当前 `cli_project/` 中长期复用；
- 配置了但无法访问的对象也必须明确报告失败/不可用，不能静默遗漏；
- 不允许用“我认为存在/应该存在”的文字代替真实观察；
- Evidence 缺失、实现文件不存在、availability 未显式声明时 Host 会拒绝 Stage 2；
- `resources` 与 `capabilities` 不能同时为空。
