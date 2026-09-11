# Task Discovery

从 Current Reality、仍然有效的 Existing Tasks 与 Current Capabilities 中发现当前真正形成的 AI 工作关系。

Reality 是任务来源。Resource 类型和 Capability 类型只提供现实与能力信息。

每个 Candidate 输出：

- task_identity
- reality_id
- description
- reality_basis
- reality_basis_refs
- identity_anchor_refs：用于 Task Identity 连续性的真实对象 / 事件 / 关系身份锚点，与当前 Evidence 引用分开
- work_relation
- expected_reality_result
- required_capability_ids

当前现实没有形成值得主动处理的新工作关系时，输出空 Candidate Set。

两个 Candidate 使用相同 work_relation 时，独立现实对象拥有各自 identity_anchor_refs，因此仍然是独立工作关系。
