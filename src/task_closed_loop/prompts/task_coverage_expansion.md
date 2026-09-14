# Task Coverage Expansion

这是弱模型的思考维度扩展层。

它不生成 Task，不生成 Candidate，也不决定最终任务数量。

只有首轮 Task Discovery 经过完整 Candidate 审查、集合审查后，合格 Candidate 少于配置阈值时，才调用本层。阈值只用于判断是否需要再次扩展思考维度，不是最终 Task 数量目标。

直接读取：

- Current Resources
- Current Reality
- Effective Existing Tasks
- Current Capabilities
- First-pass accepted candidates
- First-pass rejected contexts

`first_pass_rejected_contexts` 记录首轮已经探索但失败的方向、失败阶段、失败原因和字段问题。

Coverage Expansion 的目标不是重复首轮，而是找出**首轮没有充分展开的其它独立思考维度**。

对于已经失败的方向：

- 如果失败原因是“核心工作关系价值低、现实不成立、能力不支持”，避免换个说法重复同一方向
- 如果失败原因只是字段质量差，不把它误判为“需要一个全新的维度”；该 Candidate 会由 Task Discovery repair 阶段处理
- 只有能提出实质不同的问题空间、结果目标或现实关系时，才形成新维度

Thinking Dimension 只能从已经物化的 Current Resources / Current Reality 出发。可观察 Capability 的“先去读什么状态域”已经由 Observation Acquisition 层负责，本层不得再把 `capability:<id>` 当成新的思考维度来源。

Thinking Dimension 可以来自：

- 当前资源中另一种重要关系
- 不同对象之间另一种值得比较的角度
- 可以明显改变用户判断的其它分析维度
- 当前 Capability 可以把 Resource 转化成的另一类高价值结果
- 弱模型首轮容易忽略、但真实数据明确支持的问题空间

每个维度输出：

- dimension_id
- focus
- user_question
- value_reason
- independence_reason
- reality_basis_refs
- relevant_capability_ids

Thinking Dimension 不是 Task，不写 task_identity，不写 execution_steps，不直接输出最终任务。

如果没有更多独立、有价值的思考维度，可以返回空数组：

```json
{
  "dimensions": []
}
```

多个 Resources 同时出现不是新的 Thinking Dimension。只有它们在当前内容中存在真实关系时，才形成跨 Resource 的维度；不要为了增加思考维度而把互不相关的 Resources 拼接起来。
