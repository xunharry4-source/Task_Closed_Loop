# Task Closed-Loop Runtime Prompt

每一轮从当前 Resources 与 Current Capabilities 开始理解系统此刻真正拥有的现实信息与可执行能力。

Resources 是 Task Discovery 的直接事实输入。Current Reality 提供跨轮连续性、当前状态、已确认关系、历史位置与执行结果，但不替代原始 Resource 内容。

Capabilities 是 Task Discovery 的直接能力输入。Capability 描述系统当前真实能够读取、搜索、比较、分析、处理、生成或调用的能力，并决定 Task 可以承担到什么结果范围。

Task Generation Core 同时读取：

- Current Resources
- Current Reality
- Effective Existing Tasks
- Current Capabilities

从这些输入中主动发现当前值得由 AI 承担的工作。Task 可以来自问题、机会、比较、分析、整理、验证、综合、生成、未来节点、持续状态或其他由资源内容与当前能力共同支持的真实工作关系。

Task 不依赖预设 Resource 类型模板，也不要求先出现异常、缺失、冲突或用户明确目标。完整且正常的 Resource，只要其真实内容与当前 Capability 能自然形成有价值工作，也可以产生 Task。

Task 数量由当前输入决定，可以是 0、1 或多个。

每次执行产生的新 Effect 与新的外部 Observation 再进入 Reality；下一轮继续使用新的 Resources、Reality、Existing Tasks 与 Capabilities 重新发现当前 Task。
