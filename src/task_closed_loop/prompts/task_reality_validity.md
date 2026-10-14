# Task Reality Validity

输入：

- `resources`
- `reality`
- `capabilities`
- `task_under_review`：已形成的任务

重新依据当前 `resources`、`reality` 与 `capabilities` 判断这段工作关系现在是否仍然成立。

审查：

- `task_key` 是否仍对应当前真实工作关系
- `basis_explanation` 与 `metadata.based_on_refs` 指向的依据是否仍然存在
- 任务所依赖的资源是否仍可见、仍具有相同现实含义
- 任务若依赖 `capability:<capability_id>` 作为观察依据，对应能力是否仍然 available 且 `can_observe_state=true`
- 任务所需能力（`metadata.needed_capability_ids`）是否仍然真实可用
- 任务所依赖的现实关系是否已经完成、消失、被替换或发生实质改变

引用格式与引用路径是否存在由 Host 程序校验；你判断的是被引用的内容现在是否仍然支持这项工作。

输出 `status`，只能是：

- valid
- invalid
- replaced
- completed

并在 `evidence` / `reason` 中给出支持当前判断的现实依据。
