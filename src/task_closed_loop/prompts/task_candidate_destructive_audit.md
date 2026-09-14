# Candidate Destructive Audit

你拿到的是另一个 AI 根据同一份现实形成的 Candidate。

重新读取：

- Current Resources
- Current Reality
- Current Capabilities
- Effective Existing Tasks
- 当前 Candidate

Audit 要把两个问题分开：

1. **Task 核心是否成立**
2. **Task 核心成立，但用户输出字段是否需要修复**

### Observation Acquisition 审查边界

Runtime 会把 `origin_type=observation_acquisition` 的感知父任务与普通业务 Candidate 分开处理。这类父任务由 Capability 契约确定性地产生，只负责取得现实，不代表已经发现业务问题。

对于普通业务 Candidate：

- `capability:<id>` 只能说明某状态域可被观察，不能单独证明 sender / message / file / row / event / issue 已存在。
- 如果普通业务 Candidate 只有 `capability:<id>` 而没有已物化 Resource / Reality / Outcome 依据，应判定核心无效；正确路径是先执行 Observation Acquisition 父任务。
- 观察父任务的真实 Outcome 出现后，后续子 Task 必须依据 Outcome 中实际观察到的对象与证据形成。

## 核心有效性

以下问题可以推翻 Task 核心：

- Candidate 误读 Resource 的内容、范围、时间位置或来源性质
- Candidate 仅因为多个 Resources 同时出现，就假定它们存在现实中没有的关联、因果、比较关系或共同目标
- 把 Capability 扩张成当前不存在的能力
- 新增现实中不存在的事实、关系或结果责任
- 只是由 Resource 类型或 Capability 名称机械套出的固定用途
- 与 Existing Task 承担同一 Task Identity
- work_relation 本身没有独立现实意义
- 预期要完成的核心结果实际上不受当前 Resource / Capability 支持
- 这个工作关系本身对用户没有足够实际价值，而不是仅仅 `user_value` 文案写得差

这些情况返回 `core_valid=false`。

## 字段质量

如果底层 Task 工作关系真实、有价值、可执行，但以下字段写得不好，不要因此删除整个 Task：

- description 太泛或不清楚
- user_value 有真实价值，但表达成“有助于分析”“提高效率”等空话
- expected_reality_result 的核心结果成立，但写得不够明确或不可验证
- execution_steps 太笼统、顺序不完整、没有写清输入/操作/结果

这些情况返回：

- `core_valid=true`
- `repair_required=true`
- 在 `field_issues` 中明确说明需要修什么

如果 execution_steps 暴露出“这个 Task 实际上需要当前不存在的能力”，这属于核心无效，而不是字段修复。

## 输出

返回：

- core_valid
- repair_required
- field_issues
- challenge
- evidence
- reason

Audit 只判断与指出问题，不自己改写 Candidate，不创造新 Candidate。
