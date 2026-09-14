# Task Reality Validity

输入：

- Current Resources
- Current Reality
- Current Capabilities
- 已形成的 Task

重新依据当前 Resources、Reality 与 Capabilities 判断这段工作关系现在是否仍然成立。

审查：

- Task Identity 是否仍对应当前真实工作关系
- Reality Basis / Resource Basis 是否仍然存在
- Task 所依赖的 Resource 是否仍可见、仍具有相同现实含义
- Task 若依赖 `capability:<id>` 作为观察依据，对应 Capability 是否仍然 available 且 `can_observe_state=true`
- Task 所需 Capability 是否仍然真实可用
- Task 所依赖的现实关系是否已经完成、消失、被替换或发生实质改变

输出：

- valid
- invalid
- replaced
- completed

并给出支持当前判断的 Reality / Resource Evidence。
