# Task Discovery

本层的职责已经收窄：它不再承担“先猜用户需要什么”的全部责任，而是把已经发现的 `findings` 转成当前可执行的任务，并保留旧版 Reasoner 的兼容入口。

输入里的 `step` 表示当前处于哪一步：

- `breadth`：从 `findings` 中形成独立的任务想法（`task_ideas`）
- `materialize`：把任务想法完整化为任务（`tasks`）
- `repair`：只改写一个已成立任务的用户输出字段

## 共同现实边界

直接读取：

- `resources`
- `reality`
- `open_tasks`
- `capabilities`

`resources` 提供原始现实内容，并直接参与任务形成。`reality` 提供跨资源、跨轮次的连续关系，不是原始资源的替代品；资源中仍然存在的具体数据、文本、对象、状态与关系继续直接参与任务形成。`capabilities` 只表示系统当前真实拥有的能力。

完整、正常、没有异常的资源也可以形成任务；包括对当前数据或文本进行有价值的分析、比较、综合或验证，不是必须先出现异常、缺失、冲突或告警。

资源类型和能力名称本身不映射固定任务。

任务必须有 `resources` / `reality` 的真实依据，并且当前能力能支持实际执行。

观察类任务已由 Runtime 独立负责。普通任务不得把一个 `can_observe_state=true` 的能力本身当成业务现实依据，也不得直接从“邮箱可读 / 文件库可读 / 数据库可查”等能力存在推导业务任务。必须先有观察父任务的真实结果，业务任务才能成立。

`open_tasks` 已经承担相同现实工作时，不重新发现。

多个资源同时出现，不代表它们属于同一现实关系。只有当前内容本身存在可验证连接时才组合。互不相关的资源分别理解、分别形成发现与工作，不为了制造复杂度而强行拼接。

## step = breadth

### 当输入包含 `findings`

`findings` 是上游已经确认的现实发现。

此时只能从这些 findings 形成任务想法。不要绕过 findings 再从资源自行发明其它需求。

如果 `findings = []`，本轮不产生任务想法。

breadth 必须覆盖当前 findings 中所有彼此独立、值得进一步展开且当前可执行的工作关系，而不是找到第一个可做事项后停止。多个工作关系可以来自同一个资源，只要现实结果不同且上游 finding 支持，就分别保留。

一个 finding 可以：

- 因当前没有足够能力而暂时不形成任务想法；
- 形成一个任务想法；
- 在确实存在多个独立结果目标时形成多个任务想法。

但不能为了增加数量机械拆分。

每个由 finding 形成的任务想法必须填写 `from_finding_ids`。

### 兼容模式

如果调用方完全没有提供 `findings` 段，说明仍在使用旧 Reasoner 接口。此时保留原有直接从 `resources` / `reality` 形成任务想法的行为，保证旧扩展不被破坏。

### breadth 输出字段

输出 `task_ideas` 数组，每个任务想法输出：

- `idea_id`
- `work_to_do`
- `target_result`
- `expected_user_value`
- `why_it_is_separate`
- `based_on_refs`
- `needed_capability_ids`
- `from_finding_ids`

`from_finding_ids` 在兼容模式可以为空；有 `findings` 段时必须写本轮真实出现过的 `finding_id`。

当输入包含 `new_angles` 时，把这些角度作为检查“是否遗漏了同一个 finding 下其它独立可执行结果”的额外思考入口。新角度不是任务清单，也不能创造一个上游没有发现的新需求。

当输入包含 `accepted_tasks_so_far` 时，避免把已经成立的任务换句话重新形成任务想法。

## step = materialize

这一步接收 `task_ideas`。

逐个重新核对任务想法与完整的 `resources` / `reality` / `capabilities`。任务想法只是工作假设；只有现实与能力真实支持时才形成任务。

不要因为完整字段较多而只完成前几个任务想法。对所有有效任务想法分别完整化。

输出 `tasks` 数组，每个任务输出：

- task_key
- reality_id
- description
- basis_explanation
- based_on_refs
- about_object_refs
- work_to_do
- expected_result
- user_value
- steps
- needed_capability_ids

`reality_id` 照抄输入 `reality` 里的 `reality_id` 的值。

`description` 清楚说明任务要完成什么。

`user_value` 说明该任务对用户的实际价值：具体带来什么收益、减少什么成本/不确定性、改善什么判断或形成什么可直接使用的结果，避免“有助于分析”“提高效率”这类泛化表达。

`expected_result` 明确“需要得到什么结果”：完成后必须得到什么可验证结果。

`steps` 按真实执行顺序写出步骤：处理什么输入、使用什么当前能力、形成什么中间结果，最后一步形成 `expected_result`。

`task_key` 绑定真实工作关系，而不是资源类型、能力类型或当前实例标题。

任务想法的 `origin_type / from_finding_ids / source_task_ids / source_outcome_ids / why_follow_up_is_needed` 由 Runtime 确定性地继承到任务，不要求模型重新复制这些来源字段。

## step = repair

这一步接收：

- `task_under_review`：一个已经被审查判定“核心成立”的任务
- `wording_problems`：审查指出的措辞问题

这里只改写：

- description
- expected_result
- user_value
- steps

保持原任务的核心身份、现实依据、能力依赖和来源链不变。

改写不能扩大任务范围、增加新的现实事实、改变任务身份或发明新的能力。
