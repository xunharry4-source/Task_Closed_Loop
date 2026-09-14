# Candidate Set Destructive Audit

你拿到的是已经通过单 Candidate 审查的候选集合。

重新读取：

- Current Resources
- Current Reality
- Current Capabilities
- Effective Existing Tasks
- 当前 Candidate Set

从现实本身理解每个 Candidate 真正处理的工作关系。

比较：

- 候选是否描述同一现实工作
- 当前状态是否只是同一个 Task Identity 的不同实例
- 一个候选是否在 `work_relation + expected_reality_result` 层面已经真实覆盖另一个候选
- 同一现实是否被不同 Resource、字段或分析角度切成多个重复 Task
- Existing Task 是否已经承担相同现实工作
- 多个候选是否确实追求不同结果，因此应该保持独立

来自同一个 Resource 或使用同一个 Capability，不代表这些 Candidate 应该合并。只要它们承担的现实工作与结果不同，就保持独立。

不要因为一个 Candidate 的 description 写得很宽泛（例如“全面分析”“综合分析”）就认为它覆盖了其它 Candidate。覆盖判断主要看实际 `work_relation` 与 `expected_reality_result` 是否相同或包含。

Candidate Set Audit 的输出只基于已有 Candidate：

- keep_candidate_ids
- challenge
- evidence
- reason

Candidate Set Audit 负责保留、淘汰和去重，不负责生成新的 Candidate，也不把自身审查结果作为新的 Task 来源。
