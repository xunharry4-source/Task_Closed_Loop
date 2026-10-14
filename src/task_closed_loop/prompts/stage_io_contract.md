---

# 引用语法

- `resource:<resource_id>`：资源。只给到简介时就只写 id，不要编字段路径；
  要指具体内容就引 `reality:current#...`
- `reality:current[#字段路径]`：当前现实，身份固定写 `current`
- `task_outcome:<outcome_id>[#字段路径]`：已执行任务的结果
- `capability:<capability_id>`：功能，不带路径
- `task_outcomes` / `reality` 里 `subject_refs`、`evidence_refs`、`effect_refs` 的值：原样照抄

字段路径用 `#` 与身份分隔，`.键` 取字段、`[n]` 取下标；必须真实存在于你看到的那个对象里，Host 会逐级核对。

对：`resource:sales#payload.content_summary.columns[2]`、`reality:current#gaps[0]`
错：`current_resources[sales].payload.a`（按段名写路径）、`sales`（缺前缀）、`resource:sales.payload`（没用 #）

`about_object_refs` 只能是声明过的 subject_refs 原样，或 `resource:<resource_id>`，都不带路径。
