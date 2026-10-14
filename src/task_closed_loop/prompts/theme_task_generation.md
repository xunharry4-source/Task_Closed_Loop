# 按主题生成任务

一条任务只需满足三点：

1. 基于这个项目的**资源**：`project`、`resources`（id + 简介）与 `reality`（现在有什么、到什么程度）
2. 基于可用的**功能**：`capabilities` 只给功能名称，能做什么按你的了解判断
3. 属于当前**主题**：`theme` 与 `theme_instruction`

除此之外不设限制：不考虑可行性、谁来做、价值大小、是否足够合理——筛选由后面的独立审查负责。
要用的功能写进 `needed_functions`，清单里没有的也可以写。

要多、要全：这个主题下能想到的都写出来，同一条来源可以派生多个结果目标不同的任务，
覆盖资源的各个方面，不要自我筛选。

每条任务用 `source_kind` + `source_ref_id` 指向 `problems` / `value_opportunities` /
`capability_voids` 里的一条记录，没有来源的会被丢弃。

不编造：`based_on_refs` 必须指向输入里真实存在的内容。
