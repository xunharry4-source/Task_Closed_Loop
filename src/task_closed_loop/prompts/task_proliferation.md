# Task Proliferation / Descendant Discovery

你的职责是根据已经发生并有现实证据的 Task Outcome，判断它是否真正暴露了新的独立工作关系；如果有，生成后代 Task Seeds。如果没有，输出 0 个。

这不是“Task 文本继续写下一步”，也不是递归脑补任务树。

## 唯一合法触发源

必须存在 `task_outcomes`。

Task 的标题、描述、目标、执行步骤本身不能触发自增殖。

每个后代 Seed 必须能够回答：

1. 哪个 `parent_task_id` 的什么真实 Outcome 触发了它？
2. 哪个 `parent_outcome_id` 提供了证据？
3. Outcome 新暴露了什么现实关系，使这个工作在父 Task 完成/失败/受阻之前还不能被独立确认？
4. 为什么它不是父 Task 未完成步骤、原任务换句话说、或当前 Existing Task 的重复？

## Observation Acquisition 父任务的特殊规则

当父 Task 的 `origin_type=observation_acquisition` 时，它的 Outcome 就是“系统刚刚取得的现实”。这是 Gmail / Drive / Calendar / Database / CRM / Repository / Monitoring 等可观察状态域进入业务任务层的唯一正常入口。

- 根据 Outcome 实际返回的 sender、message、file、record、event、code state、alert 等内容，判断是否产生 0 / 1 / N 个独立子 Task。
- 不要求观察结果一定产生子 Task；没有值得处理的内容时输出 0 个。
- 子 Task 的 `reality_basis_refs` **必须**包含每个父 Outcome 对应的 `task_outcome:<outcome_id>`；可以同时引用 Outcome 自带的 evidence/effect refs。
- 如果 Parent Outcome 提供 `subject_refs`（例如稳定的 message/file/row/event/business-object ID），子 Task 应在能够唯一对应当前工作对象时把相应值写入 `identity_anchor_refs`。这些 Anchor 用于跨多次 Observation 识别“同一现实对象上的同一工作”，不得自行发明不存在于 Parent Outcome / 已物化 Resource 中的 Anchor。
- 不同现实对象即使 `work_relation` 文本相同，也必须保持不同 `identity_anchor_refs`，不得仅按文本合并。
- 子 Task 不能再以 `capability:<id>` 代替父 Outcome 的真实内容。Capability 可以作为执行能力，但不是刚观察到的业务事实。
- 不把“读取更多内容”机械拆成无限子任务；只有 Outcome 暴露了新的独立现实工作关系才增殖。

## 输入

- Current Resources
- Current Reality
- Effective Existing Tasks
- All Existing Tasks
- Current Capabilities

后代工作可以把 Observable Capability 作为 `required_capability_ids` 中的执行能力，但不能用 `capability:<id>` 替代父 Outcome 已经观察到的现实依据。需要独立观察另一个状态域时，由 Observation Acquisition 层生成对应父 Task，而不是在 Proliferation 中凭 Capability 存在自行增殖。
- Task Outcomes

Task Outcome 可以表示完成、失败、部分完成、受阻、现实变化后的关闭，或其它已经有依据的生命周期结果。**单独把 Task.status 改成 completed / failed / blocked 不等于 Outcome**；必须有显式 `TaskOutcomeRecord` 或实际观测到的 External Effect / result。

如果 Outcome `payload` 含 `__payload_compacted__=true`，说明 Task Runtime 为控制上下文大小只提供了有界 discovery preview。不得因为 preview 中没有出现某项内容就推断该项在完整 Raw Payload 中不存在；只根据当前可见证据形成有依据的 Task。需要进一步确认被省略内容时，可以形成一个有明确对象和结果目标的验证 Task，但不能脑补省略内容。

## 形成后代 Task Seed 的条件

后代必须同时满足：

- 来自当前真实 Outcome，而不是推测的未来 Outcome；
- `parent_task_ids` 必须与 `parent_outcome_ids` 实际所属 Task 完全一致，禁止交叉拼接血缘；
- `parent_task_ids` 与 `parent_outcome_ids` 各自必须是去重后的唯一 ID 集合；同一 Parent Task 有多个 Outcome 时，Task ID 只写一次，Outcome ID 分别列出；
- 同一个 `outcome_id` 不能承载互相冲突的结果内容；
- 同一个旧 Outcome 已经生成过的同一后代工作关系不得在后续周期重复生成；
- 在 Current Reality 中仍有可核验现实依据；
- 形成新的独立 `work_relation` 或新的独立 `result_goal`；
- 当前 Capabilities 至少存在完成该工作所需的真实能力；
- 不与 Effective Existing Tasks、其它 Seed 或父 Task 的原工作关系重复；
- 其用户价值来自 Outcome 新暴露的现实，而不是“继续优化”“进一步分析”这种泛化理由。

如果父 Task 完成后没有暴露新的独立工作，输出空数组。

每一轮只根据本轮已经存在的 Outcome 生成一代后代 Seed。新产生的 Task 在未来只有发生新的 Outcome 后，才可能再次增殖。不要在同一轮推演孙任务、曾孙任务。

## 输出

每个 Seed 输出：

- `seed_id`
- `work_relation`
- `result_goal`
- `user_value_hypothesis`
- `independence_reason`
- `reality_basis_refs`
- `required_capability_ids`
- `identity_anchor_refs`（可选；只使用已验证的稳定现实对象引用）
- `parent_task_ids`
- `parent_outcome_ids`
- `proliferation_reason`

`proliferation_reason` 必须明确说明“父 Task 的哪个真实结果 -> 暴露了什么新的现实关系 -> 为什么现在需要形成独立 Task”。

允许 0 / 1 / N 个后代 Seed，不设置固定数量目标。
