# Candidate Set Destructive Audit

把已经单独通过审查的 Candidate 作为一个集合重新观察。

尝试发现：

- 同一现实工作关系被重复发现
- 一个工作关系被碎片化成多个 Candidate
- 多个 Candidate 实际指向同一个 Task Identity
- Candidate 之间依赖互相循环或只是彼此改写

返回应该保留的 candidate_id 集合，以及支持该判断的现实关系。
