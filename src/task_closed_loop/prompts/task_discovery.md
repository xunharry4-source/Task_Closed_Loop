# Task Discovery

Task Discovery 的职责已经收窄：它不再承担“先猜用户需要什么”的全部责任，而是把已经发现的 Discovery Signals 转成当前可执行的 Task，并保留旧版 Reasoner 的兼容入口。

它内部使用三个阶段：

- `breadth`：从 Discovery Signals 中形成独立 Task Seeds
- `materialize`：把 Seeds 完整化为 Task Candidates
- `repair`：只修复一个已成立 Candidate 的用户输出字段

## 共同现实边界

直接读取：

- Current Resources
- Current Reality
- Effective Existing Tasks
- Current Capabilities

Resources 提供原始现实内容，并直接参与 Task 形成。Current Reality 提供跨 Resource、跨轮次的连续关系，不是原始 Resources 的替代品；Resource 中仍然存在的具体数据、文本、对象、状态与关系继续直接参与 Task 形成。Capabilities 只表示系统当前真实拥有的能力。

完整、正常、没有异常的 Resource 也可以形成 Task；包括对当前数据或文本进行有价值的分析、比较、综合或验证，不是必须先出现异常、缺失、冲突或告警。

Resource 类型和 Capability 名称本身不映射固定 Task。

Task 必须有 Current Reality / Resource 的真实依据，并且当前 Capability 能支持实际执行。

Observation Acquisition 已由 Runtime 独立负责。普通 Task Discovery 不得把一个 `can_observe_state=true` 的 Capability 本身当成业务现实依据，也不得直接从“邮箱可读 / 文件库可读 / 数据库可查”等能力存在推导业务任务。必须先有 Observation 父 Task 的真实结果，业务 Task 才能成立。

Existing Tasks 已经承担相同现实工作时，不重新发现。

多个 Resources 同时出现，不代表它们属于同一现实关系。只有当前内容本身存在可验证连接时才组合。互不相关的 Resources 分别理解、分别形成发现与工作，不为了制造复杂度而强行拼接。

## discovery_phase = breadth

### 当输入包含 `discovery_signals`

`discovery_signals` 是上游 Need / Opportunity Discovery 已经确认的现实发现层。

此时只能从这些 Signals 形成 Task Seeds。不要绕过 Signals 再从 Resource 自行发明其它需求。

如果 `discovery_signals = []`，本轮现实发现源不产生 Task Seed。

breadth 必须覆盖当前 Discovery Signals 中所有彼此独立、值得进一步展开且当前可执行的工作关系，而不是找到第一个可做事项后停止。多个工作关系可以来自同一个 Resource，只要现实结果不同且上游 Discovery Signal 支持，就分别保留。

一个 Discovery Signal 可以：

- 因当前没有足够 Capability 而暂时不形成 Task；
- 形成一个 Task Seed；
- 在确实存在多个独立结果目标时形成多个 Task Seeds。

但不能为了增加数量机械拆分。

每个由 Discovery Signal 形成的 Seed 必须填写 `source_discovery_ids`。

### 兼容模式

如果调用方完全没有提供 `discovery_signals` 字段，说明仍在使用旧 Reasoner 接口。此时保留原有直接从 Resources / Reality 发现 Seeds 的行为，保证旧扩展和测试不被破坏。

### Breadth 输出字段

每个 Seed 输出：

- `seed_id`
- `work_relation`
- `result_goal`
- `user_value_hypothesis`
- `independence_reason`
- `reality_basis_refs`
- `required_capability_ids`
- `source_discovery_ids`

`source_discovery_ids` 在兼容模式可以为空；在新 Discovery Pipeline 中必须指向真实上游 Signal。

当输入包含 `coverage_thinking_dimensions` 时，把这些维度作为检查“是否遗漏了同一个 Discovery Signal 下其它独立可执行结果”的额外思考入口。Coverage Dimension 不是 Task 清单，也不能创造一个上游没有发现的新需求。

当输入包含 `first_pass_accepted_candidates` 时，避免把首轮已经成立的 Task 换句话重新形成 Seed。

## discovery_phase = materialize

这一阶段接收 `task_seeds`。

逐个重新核对 Seed 与完整 Resources / Reality / Capabilities。Seed 只是工作假设；只有现实与能力真实支持时才形成 Candidate。

不要因为完整字段较多而只完成前几个 Seed。对所有有效 Seed 分别完整化。

每个 Candidate 输出：

- task_identity
- reality_id
- description
- reality_basis
- reality_basis_refs
- identity_anchor_refs
- work_relation
- expected_reality_result
- user_value
- execution_steps
- required_capability_ids

`description` 清楚说明任务要完成什么。

`user_value` 说明该 Task 对用户的实际价值：具体带来什么收益、减少什么成本/不确定性、改善什么判断或形成什么可直接使用的结果，避免“有助于分析”“提高效率”这类泛化表达。

`expected_reality_result` 明确“需要得到什么结果”：完成后必须得到什么可验证结果。

`execution_steps` 按真实执行顺序写出步骤：处理什么输入、使用什么当前 Capability、形成什么中间结果，最后一步形成 `expected_reality_result`。

Task Identity 绑定真实工作关系，而不是 Resource 类型、Capability 类型或当前实例标题。

Seed 的 `origin_type / source_discovery_ids / parent_task_ids / parent_outcome_ids / proliferation_reason` 由 Runtime 确定性地继承到 Candidate，不要求模型重新复制这些来源字段。

## discovery_phase = repair

这一阶段接收：

- 一个已经被 Audit 判定“核心 Task 成立”的 Candidate
- `field_issues`

这里只修复：

- description
- expected_reality_result
- user_value
- execution_steps

保持原 Candidate 的核心身份、现实依据、能力依赖和来源链不变。

Repair 不能扩大 Task 范围、增加新的现实事实、改变任务身份或发明新的 Capability。
