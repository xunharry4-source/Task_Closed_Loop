# Candidate Set Destructive Audit

你拿到的 `tasks_under_review` 是已经通过单任务审查的任务集合。

重新读取：

- `resources`
- `reality`
- `capabilities`
- `open_tasks`
- `tasks_under_review`

从现实本身理解每个任务真正处理的工作关系。

比较：

- 任务是否描述同一现实工作
- 当前状态是否只是同一个 `task_key` 的不同实例
- 一个任务是否在 `work_to_do + expected_result` 层面已经真实覆盖另一个任务
- 同一现实是否被不同资源、字段或分析角度切成多个重复任务
- `open_tasks` 中的任务是否已经承担相同现实工作
- 多个任务是否确实追求不同结果，因此应该保持独立

来自同一个资源或使用同一个能力，不代表这些任务应该合并。只要它们承担的现实工作与结果不同，就保持独立。

不要因为一个任务的 description 写得很宽泛（例如“全面分析”“综合分析”）就认为它覆盖了其它任务。覆盖判断主要看实际 `work_to_do` 与 `expected_result` 是否相同或包含。

集合审查的输出只基于已有任务：

- keep_ids：要保留的任务的 `candidate_id`
- challenge
- evidence
- reason

集合审查负责保留、淘汰和去重，不负责生成新任务，也不把自身审查结果作为新的任务来源。
