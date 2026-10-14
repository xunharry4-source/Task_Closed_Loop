# Existing Task Continuity V1

输入段：
- `reality`：当前现实
- `tasks_to_recheck`：需要重新判断的已有任务

对每个已有任务判断它与当前现实的真实关系。

输出：
- `still_open_task_ids`：仍然有效的任务
- `completed_task_ids`：已完成的任务
- `invalid_task_ids`：已失效的任务
- `superseded_task_ids`：已被当前现实取代的任务

`task_key` 对应真实世界中的工作关系。
同一工作关系在现实对象、证据、时间、责任人或执行实例变化时仍可保持连续。
真实工作关系发生拆分、合并、替换或消失时，按当前现实重新建立工作关系。

当前现实是判断依据；已有任务本身只提供连续性参照。
