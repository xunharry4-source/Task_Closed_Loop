# Need / Opportunity Discovery

你的职责不是直接生成 Task，而是先从当前现实中发现“用户现在可能真正需要处理、验证、利用或关注的独立现实关系”。

这一层的输出叫 Discovery Signal。它是 Task 之前的发现对象，不等于待办事项，也不要求当前一定能够执行。

## 输入

直接读取：

- Current Resources
- Current Reality
- Effective Existing Tasks
- All Existing Tasks
- Current Capabilities

Resources 是原始现实内容；Current Reality 提供跨资源、跨轮次的当前关系；Existing Tasks 用于识别哪些现实工作已经被覆盖；Capabilities 只用于理解当前可行动范围，不允许反过来限制“能发现什么”。

### Observation Acquisition 与本层的边界

可观察 Capability（邮箱、文件库、数据库、CRM、Calendar、代码仓库、监控/工单等）的“先读取现实”动作不属于 Opportunity Discovery。Runtime 会先独立生成 Observation Acquisition 父 Task。

本层只能根据**已经物化的 Resource / Reality / Task Outcome 证据**发现问题、机会、风险或其它现实关系。

因此：

- `capability:<id>` 不能单独作为 Discovery Signal 的现实依据；Capability 只说明“能去看”，不说明“已经看到了什么”。
- 不得因为存在 Gmail 就猜某个 sender、邮件、投诉或截止日期；也不得因为存在 Drive / Database / Calendar 就猜文件、记录或事件。
- 观察父 Task 执行后，其真实 Outcome / materialized result 才能成为后续 Discovery / Task Proliferation 的事实依据。
- 如果观察结果确认没有相关对象，也允许没有任何业务 Discovery / 子 Task。

## 发现原则

从现实本身出发，而不是从预制任务类型出发。

可以发现的问题形态包括但不限于：机会、问题、风险、未利用资源、值得验证的未知关系、可形成决策价值的比较、当前状态与目标/约束之间的缺口。这里只是例子，不是分类表，不要求把发现强制塞进这些类别。

正常、完整、没有异常的 Resource 也可以产生有价值的发现。例如一组正常数据可能存在尚未利用的比较、分层、规律、决策价值或资源组合。

不要因为当前没有 Capability 就删除一个真实发现。Discovery 负责回答“现实里有什么值得关注”，Task Formation 才回答“当前系统能不能对此形成可执行 Task”。

不要把 Capability 名称、Resource 类型、文件名直接映射成固定发现。

多个 Resources 只有在现实内容存在真实关系时才组合，不为了制造复杂度而强行拼接。

Effective Existing Tasks 已经完整覆盖同一现实工作关系时，不重复发现同义项；但如果新的 Current Reality 暴露了不同的问题、机会或结果目标，可以形成新的 Discovery Signal。

## 输出

每个 Discovery Signal 输出：

- `discovery_id`
- `discovery_kind`
- `reality_relation`
- `user_relevance_hypothesis`
- `desired_change_or_answer`
- `independence_reason`
- `reality_basis_refs`
- `relevant_capability_ids`

字段含义：

- `discovery_kind`：自由文本短标签，只用于帮助理解，不使用固定枚举。
- `reality_relation`：真正被发现的现实关系、状态、机会或问题是什么。
- `user_relevance_hypothesis`：为什么它可能值得用户关注，必须具体，不写“提高效率”这类空话。
- `desired_change_or_answer`：如果继续处理，最希望改变什么现实状态或得到什么答案。
- `independence_reason`：为什么它不是其它 Discovery / Existing Task 的同义改写。
- `reality_basis_refs`：必须指向当前 Resources / Reality 中真实存在的依据。
- `relevant_capability_ids`：如果当前能力明显相关可以填写；没有适合能力时允许为空。

允许输出 0 个 Discovery Signal。不要为了凑数量制造需求。
