# 提示词：每一步改哪个文件

提示词正文都在本目录，**一个角色一个 `.yml`**。  
索引在 `src/task_closed_loop/prompts/manifest.yml`（角色名、role、共享段）；一般改提示词不用动它，除非新增角色。

系统只读每个文件里的 `提示词` 与 `设置`；`说明` / `变量` 给人看，不进模型。

---

## 主路径（V1.4 六步）

### 第一步：用户配置

不改本目录提示词。改：

| 文件 | 作用 |
|---|---|
| `config/preflight_sources.yml` | 工作目录路径、功能名、用哪个 CLI、`analyze` 模式 |

---

### 第二步：CLI 分析资源与功能

| 文件 | 作用 |
|---|---|
| `preflight_source_analysis.yml` | 交给 CLI 的整段说明：在 `cli_project/` 里写分析代码，按资源/功能两个模版填结果 |

说明：没有「本轮输入」，**不支持** `{{变量名}}`。改完后，已初始化过的单元可能因指纹变化需要重跑（或设 `analyze: always`）。

---

### 第三步：生成项目

| 文件 | 作用 |
|---|---|
| `project_discovery.yml` | 把资源（id + summary）归纳成项目：`project_id` / `name` / `description` / `resource_ids` |

---

### 第四步：问题 / 价值 / 需求 → 主题

三者互不读对方结论；主题那一次同时看三层。

| 文件 | 作用 |
|---|---|
| `problem_discovery.yml` | 只找问题：未知盲区 / 已知缺陷 |
| `value_discovery.yml` | 只找价值：全新方案 / 增量方案 |
| `demand_discovery.yml` | 只找需求：现有功能盖不住的能力缺口 |
| `theme_planner.yml` | 整理资源信息 + 固定主题 + 推导主题；主题要带 `source_refs` 血缘 |

---

### 第五步：按主题生成任务

| 文件 | 作用 |
|---|---|
| `theme_task_generation.yml` | 每个主题各调用一次；只按资源、功能、主题出任务，不做筛选 |

---

### 第六步：审核任务

| 文件 | 作用 |
|---|---|
| `task_candidate_destructive_audit.yml` | 单条·核心：工作关系成不成立（`is_valid_work`） |
| `task_candidate_field_audit.yml` | 单条·字段：核心已通过后，要不要改写文案（`needs_rewrite`） |
| `task_candidate_set_audit.yml` | 成组：重复、冲突、覆盖；只保留 / 淘汰，不生成新任务 |
| `task_reality_validity.yml` | 定稿后再核对任务与资源/功能是否仍对得上 |

单条顺序：核心审 →（通过后）字段审 → 需要时改写并只复检字段 → 成组审。

---

### 数量不足时的补充（回到第六步前）

| 文件 | 作用 |
|---|---|
| `task_coverage_expansion.yml` | 合格任务过少时，生成新的思考角度（不当任务）；每个角度再当主题走第五步，然后强制回第六步 |

---

## 共享段（被 includes 进别的角色）

| 文件 | 作用 | 什么时候改 |
|---|---|---|
| `stage_io_contract.yml` | 引用语法（`resource:` / `reality:` / …） | 改引用规则、字段路径写法时 |
| `runtime_context.yml` | 运行时上下文说明 | 一般不用为六步流程改 |
| `output_template.yml` | 输出模版说明 | 一般不用为六步流程改 |

多数主路径角色在 manifest 里 `includes: [stage_io_contract]`。某个角色不要共享段时，在该文件 `设置.includes: false`。

---

## 旧链条专用（默认 `first_step.mode: skill_chain` 时不要当主路径改）

仅在 `config/task_generation.yml` 里 `first_step.mode: legacy_discovery` 时走这些：

| 文件 | 作用 |
|---|---|
| `reality_builder.yml` | 旧链：构建现实 |
| `existing_task_continuity.yml` | 旧链：既有任务是否仍成立 |
| `need_opportunity_discovery.yml` | 旧链：需要与机会发现 |
| `task_discovery.yml` | 旧链：发现任务候选 |
| `task_proliferation.yml` | 旧链：从任务结果派生后续任务 |

---

## 改完提示词还要动索引吗？

| 情况 | 要不要改 `manifest.yml` / `config/llm.yml` |
|---|---|
| 只改某个已有角色的正文或设置 | 不用 |
| 新增一个角色文件 | 要：写入 manifest；若适配器用了独立 `role_key`，还要在 `config/llm.yml` 的 `roles` 里映射 |
| 改角色文件名 | 要：同步 manifest（及 llm roles） |

变量名写死在 `src/task_closed_loop/llm/prompt_template.py` 的 `VARIABLES`；不能在 yml 里自造新变量名，只能使用已有的 `{{中文名}}` / `{{英文别名}}`。
