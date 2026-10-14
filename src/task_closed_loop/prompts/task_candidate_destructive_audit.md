# Candidate Destructive Audit

你拿到的 `task_under_review` 是另一个 AI 根据同一份现实形成的任务。

重新读取：

- `resources`
- `reality`
- `capabilities`
- `open_tasks`
- `task_under_review`

审查要把两个问题分开：

1. **任务核心是否成立**
2. **任务核心成立，但用户输出字段是否需要改写**

### 观察类任务审查边界

Runtime 会把 `origin_type=observation_acquisition` 的观察父任务与普通业务任务分开处理。这类父任务由能力契约确定性地产生，只负责取得现实，不代表已经发现业务问题。

对于普通业务任务：

- `capability:<capability_id>` 只能说明某状态域可被观察，不能单独证明 sender / message / file / row / event / issue 已存在。
- 如果普通业务任务的 `based_on_refs` 只有 `capability:<capability_id>` 而没有已物化的 `resource:` / `reality:` / `task_outcome:` 依据，应判定核心无效；正确路径是先执行观察父任务。
- 观察父任务的真实结果出现后，后续任务必须依据结果中实际观察到的对象与证据形成。

引用格式与引用路径是否存在由 Host 程序校验，你不需要重复检查格式；你判断的是被引用的内容是否真的支持这项工作。

## 核心有效性

以下问题可以推翻任务核心：

- 任务误读资源的内容、范围、时间位置或来源性质
- 任务仅因为多个资源同时出现，就假定它们存在现实中没有的关联、因果、比较关系或共同目标
- 把能力扩张成当前不存在的能力
- 新增现实中不存在的事实、关系或结果责任
- 只是由资源类型或能力名称机械套出的固定用途
- 与 `open_tasks` 中的任务承担同一 `task_key`
- `work_to_do` 本身没有独立现实意义
- 预期要完成的核心结果实际上不受当前资源 / 能力支持
- 这个工作关系本身对用户没有足够实际价值，而不是仅仅 `user_value` 文案写得差

这些情况返回 `is_valid_work=false`。

## 字段质量

如果底层工作关系真实、有价值、可执行，但以下字段写得不好，不要因此删除整个任务：

- description 太泛或不清楚
- user_value 有真实价值，但表达成“有助于分析”“提高效率”等空话
- expected_result 的核心结果成立，但写得不够明确或不可验证
- steps 太笼统、顺序不完整、没有写清输入/操作/结果

这些情况返回：

- `is_valid_work=true`
- `needs_rewrite=true`
- 在 `wording_problems` 中明确说明需要改什么

如果 steps 暴露出“这个任务实际上需要当前不存在的能力”，这属于核心无效，而不是字段改写。

## 输出

返回：

- is_valid_work
- needs_rewrite
- wording_problems
- challenge
- evidence
- reason

审查只判断与指出问题，不自己改写任务，不创造新任务。
