# Task Closed-Loop Architecture

当前发布版本：**V1.4｜六步流程**  
冻结架构版本：**Architecture Contract V1.2 / Architecture Locked**

V1.4 按用户口述的六步流程重做了**实现与提示词**，没有改动冻结架构：7 Stage 顺序、Stage Contract、
Pipeline 依赖方向、`config/architecture_contract.yml` 全部保持 1.2。
架构锁断言的是 7 个 `(number, id)` stage 记录、`task_files` 精确等值、两个 `standard_outputs` 路径、
三个代码边界路径与规则/不变量子集；它不读 `stage_2.analysis_outputs`，所以第二步把两套分析文件
合成一份 Host 回执也不需要升级版本。

## 1. 不可漂移的架构边界

```text
pipeline/
    ↓ only depends on
contracts/
    ↑ implemented by
implementations/
    ↑ uses
preflight / projects / llm / tasks / capability_runtime / other domain modules
```

1. `pipeline/production.py`：只定义 7 Stage 调用顺序与 Stage 7 → Stage 4 回边；
2. `contracts/`：阶段输入/输出 DTO 与 Protocol；
3. `implementations/`：可替换的业务实现。

除非用户明确要求"改变系统架构"，普通修复不得改 Stage 顺序、不得在 Pipeline 里 import 具体实现、
不得新增正式旁路。长期规则：**改接口的实现，不改 Pipeline**。

## 2. 固定接口

| Stage | Contract | 默认实现 |
|---|---|---|
| 1 | `CliProjectManager` | `implementations/cli_project/` |
| 2 | `ResourceCapabilityAnalyzer` | `implementations/resource_analysis/` |
| 3 | `InitialTaskGenerator` | `implementations/task_generation/skill_chain.py` |
| 4 | `TaskAuditor` | `implementations/task_audit/` |
| 5 | `TaskCountPolicy` | `implementations/task_count/` |
| 6 | `TaskDimensionGenerator` | `implementations/task_dimensions/` |
| 7 | `TaskRegenerator` | `implementations/task_regeneration/` + `skill_chain.ProjectChainTaskRegenerator` |

## 3. 六步流程与 7 Stage 的映射

```text
第一步 用户配置                     config/preflight_sources.yml
   ↓
Stage 1 | CLI 工作目录               missing -> Host 复制模板 / valid -> 复用 / invalid -> READY CLI 原位修复
   ↓
Stage 2 | 第二步：分析并填模版        CLI cwd = cli_project/，Host 执行分析代码并校验
   ↓                                 -> generated/resources.generated.yml
   ↓                                 -> generated/capabilities.generated.yml
第三步 生成项目                      projects/discovery.py（Stage 2 之后、按项目起流水线之前）
   ↓
Stage 3 | 第四、五步                 问题 / 价值 / 需求（各 1 次，互不读对方）
   ↓                                 -> 主题（1 次，读三层）
   ↓                                 -> 每个主题 1 次 -> 未审查候选（血缘继承自主题）
Stage 4 | 第六步：独立审核
   ↓
Stage 5 | 只统计通过审核的业务任务
   ├─ 够 -> 结束
   └─ 过少
        ↓
Stage 6 | 生成思考角度
        ↓
Stage 7 | 每个角度当作一个新主题重新生成
        ↓
      Stage 4（强制）
```

每个项目各跑一次完整的 Stage 1–7（候选被硬绑定在单一 `reality_id` 上）。Stage 1 幂等复用；
Stage 2 的真实扫描全程只执行一次，由 `ProjectStage2Cache` 共享并按项目切分；
多项目时产物写在 `generated/<project_id>/`，单项目仍写 `generated/`。

## 4. 第一步：配置只有三件事

```yaml
preflight_inputs:
  cli: codex          # codex（chatgpt）/ gemini / claude
  analyze: auto       # auto / always / never
  directories: []     # 只写路径
  functions: []       # 只写名字
```

配置里没有 id、description、operations、entities、scope、secret_refs、kind——这些全部由第二步的
分析得出或根本不需要。资源 id 由目录名生成（`resource_id_for_directory`，重名时用上层目录区分）。

`cli` 一处决定两件事：第二步用哪个 CLI（`implementations/resource_analysis/cli.py`），
以及第四~六步推理适配器的默认值（`cli_choice.configured_cli_engine` → `llm/factory.py`）。
`TASK_LLM_ADAPTER` / `AUDIT_LLM_ADAPTER` 仍可单独覆盖；`claude` 没有推理适配器，会明确报错而不是静默回退。

## 5. Stage 1：项目检查 / 修复

默认 `<project_root>/cli_project/`。三条路径固定：`missing` 复制 `cli_project_template/`；
`valid` 直接复用；`invalid` 由 CLI 在原目录 `cwd=cli_project/` 修复，Host 重新 verify。
Host 不允许在 `invalid` 分支偷偷复制模板掩盖结构错误。

Host 拥有的文件（`capability_runtime/workspace.py` 的 `HOST_OWNED_FILES`）每轮由
`fill_host_owned_files()` 对齐：内容不一致时覆盖，并把旧文件备份成 `<名字>.superseded`。
CLI 可以写分析实现，但改不动统一接口与入口。

CLI 状态模型：`MISSING / INSTALLED / NEEDS_AUTH / UNHEALTHY / READY`。`--version` 只判断基础安装状态，
READY 必须另外通过认证/健康探测。默认 Engine 允许 fallback；显式指定时不暗中切换。

## 6. Stage 2：第二步是初始化，不是每轮重跑

```text
cli_project/analysis/templates.py        两个模版（Host 拥有）
cli_project/analysis/main.py             统一入口 + 手动触发（Host 拥有）
cli_project/analysis/resources/<id>.py   CLI 写：def analyze(target, context) -> dict
cli_project/analysis/functions/<名字>.py  CLI 写：def analyze(target, context) -> dict
```

Host 用 `python -I` 运行入口，只把 `cli_project/analysis/` 与 `cli_project/` 两个根加入模块路径，
因此 CLI 可以写多文件模块，不必把逻辑塞进单个 `main.py`。

三态 `analyze`（`preflight.cli_preflight.analysis_mode`）：

- `auto`（默认）：**指定目录里没有这一项的数据才跑**，已经有了就跳过（`reuse_saved`）；
  新增目录/功能时只初始化新增的那一项。
- `always`：全部重新初始化。
- `never`：从不调用 CLI，只用已保存的数据；什么都没保存就报错。

入口强制实现手动触发：`--list / --directory / --function / --inputs / --all / --write`。
`--write` 按 id 合并进标准输出，缺少分析实现时返回 `availability: failed` 的条目。
已初始化过哪些单元记录在 `cli_project/state/stage2_build_state.yml`（指纹 = 单元配置 + 提示词）。

### 6.1 两个模版

资源：`id / type / summary / availability / payload / metadata.source_input_ids`
功能：`id / identity / availability / metadata.source_function_id`

`summary` 是后续每一步唯一会读到的那句话：这是什么、现在有什么、到什么程度。
`identity` 只写功能的**身份**——谁开发的、是什么类型的工具；**不写它能做什么**。
二者都由 `analysis/templates.py` 的构造函数产出，字段固定，不手拼字典。

已删除：`resource_analysis` / `function_analysis` 两套模版与 `results/*.analysis.yml`、
结构化 evidence 闸门、`implementation_files` 校验、`operations` 白名单、
`available_operations` / `target_scope` / `can_observe_state` / `observable_state` 必填、
两处 availability 互相校对、按操作拆能力。它们是今天三次失败里两次的直接原因
（30 秒探针超时整单元失败；两处 availability 不一致整单元失败），且都不被架构锁要求。

### 6.2 保留的闸门

- **覆盖**：每个配置的目录与功能都必须出现；访问不了也要显式 `unavailable` / `failed`，不得静默遗漏。
- **本地目录由 Host 自己重扫**：文件数、目录数、相对文件树、SHA-256 tree digest 由 Host 生成，
  CLI 自报的本地观察不具有事实权威。
- `availability` 必须显式且合法；`summary` 必填；血缘 id（`source_input_ids` / `source_function_id`）必须真实。
- `payload` 递归拒绝原始定位/连接信息（见 §7）。

### 6.3 产物

```text
cli_project/generated/resources.generated.yml        架构锁要求的标准输出
cli_project/generated/capabilities.generated.yml     架构锁要求的标准输出
cli_project/analysis/results/stage2.analysis.yml     Host 写的回执
```

`ResourceCapabilityResult` 的 `resource_analysis_path` 与 `function_analysis_path` 都指向那份回执，
因此 `contracts/` 不动。

## 7. Stage 2 → 任务层安全边界

任务层不连接外部系统，所以标准 Resource/Capability 不能重新携带传输信息。
原始路径、URI、对象定位与连接材料属于 Preflight 的 **Resource Reference**，任务层不接受未物化的引用。

```text
path / root / uri / url / dsn / connection / connection_string
credentials / password / token / api_key / secret / access_token / refresh_token
client_secret / private_key
```

`payload` 与 capability `target_scope` 递归拒绝上述结构化字段；自然内容字段（正文、文本、summary）
可以提到 URL，验证器区分"内容里的 URL"与"用于连接的 URL 字段"。

## 8. 第三步：项目由系统生成（`projects/`）

`projects/discovery.py` 一次调用：输入全部资源（id + summary）与功能名，输出
`project_id / name / description / resource_ids`。用户不再维护项目清单
（`config/projects.yml` 与 `prompts/project_assignment.md` 已删除）。

- **资源是唯一的隔离边界**：资源按项目划分，**一份资源可同时属于多个项目**（数据允许共享）；
  功能不分项目，所有项目共用全部功能。
- **id 稳定**：注册表 `cli_project/state/projects.yml`。沿用旧 id 的条件依次是——模型给的 id 已注册；
  同名且至少共用一个资源；资源集合**唯一**匹配某个旧项目（共享资源会让集合匹配产生歧义，
  歧义时必须新建而不是乱认）。消失的项目保留在注册表里不删。
  资源指纹没变时直接复用上一轮结果，不再提问。
- **切分**：`projects/grouping.py` 从标准输出的 `metadata.source_input_ids` 还原资源归属再切分
  （`ResourceSnapshot` 没有 metadata 字段，归属在 Stage 2 → Stage 3 边界会丢，所以从标准文件读回），
  同时产出投影：`resource_briefs()` = `{resource_id, summary, note}`，
  `capability_briefs()` = `{function, identity}`，`capability_names()` = 纯名字。

## 9. 第四、五步：Stage 3 实现内的链条

```text
项目的资源(简介) + 功能(名字 + 身份) + 项目说明
        ├── 问题发现   UNKNOWN_BLINDSPOT / KNOWN_DEFECT
        ├── 价值发现   NOVEL_PARADIGM / INCREMENTAL_SCHEME
        └── 需求发现   BREAKTHROUGH_NEED / BASELINE_NEED
                ↓   三者各一次调用，互不读对方的结论
            主题规划   5 固定（优化·推进·收益·探针·破局）+ 2–5 推导
                ↓   每个主题各一次独立调用
              任务
```

- **三路独立**：问题、价值、需求互不读对方结论——否则一层的盲区会变成下一层的起点。
  主题那一次调用同时看三层，因为主题要覆盖它们并承担血缘。
- **主题**：5 个固定主题由 Host 给定，探针与破局不可省略（模型要求跳过时记录并照常提问）；
  推导主题 2–5 个，按上周 `yield_count` 轮换。每个主题一次独立调用，互不污染上下文。
- **任务只有三个基准**：资源、功能、主题。提示词里不附加别的限制——可行性、谁来做、价值大小、
  是否"合理"都不在生成期判断。用户的"不考虑"清单（`exclusions`）由 Host 在生成之后过滤，不写进提示词。
- **第一遍要多、要全**：以数量与覆盖面为目标，不自我筛选；"可能不合理/没意义/价值不大"不是放弃的理由。
  唯一不放松的是**不得编造**：每条记录与任务都要有真实存在的依据引用。
- **功能只给名字与身份**：`{function, identity}`，不给操作清单、`target_scope`、`input_schema`。
  模型对这些工具本来就有完整认知，不认识的会自己去查；写死能力只会让它以为功能就只有那几项。
  `_capability_record` 因此直接丢掉分析写的 `description`。
  任务写 `needed_functions`（功能名），Host 再映射回 Stage 2 实际报告的 capability id 交给 Stage 4。
- **资源只给简介**：`resource_id` + `summary`（+ 本项目的切分说明）。完整 `payload` 只进 Stage 4 审核。
- **血缘继承自主题**：主题带 `source_refs`（它覆盖的问题/价值/需求 id），任务不再自己引用三层，
  Host 据主题写任务的 `source_table` / `source_id`；没标注来源的主题继承本项目来源池并标记
  `lineage_inherited`。任务库的 `trg_tasks_source` 触发器因此照旧满足，**不碰用户的库结构**。
- **层级与类型由 Host 判定**：TIER_1 / TIER_2、UNKNOWN_PROBE / NEW_PARADIGM / FIX_AUDIT /
  CREATIVE_PROGRESS / DECISION_ANALYSIS / MECHANISM_ITERATION 不由模型填。

### 9.1 没有现实层

六步流程里没有"构建现实"这一步，因此**不再调用 reality builder**。资源的 `summary` 已经就是
"现在有什么、到什么程度"，Host 确定性地构造 `RealitySnapshot`：
`reality_id = <project_id>-<week>`、`current_facts = {resource_id: summary}`（`_host_reality`）。于是

- `ProductionPipelineResult.reality`、`PipelineCycleView` 等契约字段仍有值 → `contracts/` 不动；
- `reality_id` 绑定校验（`generation_audit` / `reality_validity`）天然成立（Host 统一赋值）；
- 每个项目少一次调用，也不再有"把 141 KB payload 读成一段话"的中间环节。

引用以 `resource:<id>` 为主，`reality:current#facts.<resource_id>` 仍可用。
旧链条（`first_step.mode: legacy_discovery`）仍走 reality builder 与旧引擎。

## 10. 第六步与补充轮（Stage 4–7）

- Stage 4：独立审核，实现不得合并回 Stage 3；输入含资源完整 `payload`。
  单条语义审分两步调用：核心成立（`task_candidate_destructive_audit`）→
  字段质量（`task_candidate_field_audit`）；字段改写后只复检字段。
- Stage 5：只统计审核通过的业务任务；Observation Task 不能拿来凑数量。
- Stage 6：只有任务过少才生成思考角度。
- Stage 7：每个角度作为一个推导主题重新提问（同一角度只问一次），来源仍限定在 Stage 3 已确认的
  问题/价值/需求（`ProjectChainTaskRegenerator`）；所有新候选强制回 Stage 4。

旧 `Coverage Expansion` 不允许在 Stage 3 偷跑 Dimensions。

## 11. 任务库（长期记忆）

`config/task_store.yml` 指定任务库（默认参谋 SQLite）。项目、问题、价值、需求、主题在第四步写入；
任务在整条流水线跑完后写入，并回写来源 `status='已转任务'`。

- `task_key = sha256(entity_id, task_type, core_target)`：同 key 的未结任务只 `times_proposed+1`；
  被搁置且未到期的跳过；命中 `exclusions` 的候选在生成期即丢弃。
- 写操作统一走 `_write()` 上下文管理器：任何一次被触发器拒绝的写入都回滚，不会留下未结束的事务
  把后面的写入全部堵死。
- **对已存在的任务库只写数据，绝不 CREATE / ALTER**；缺表直接报错并指出表名。

## 12. 模型调用留痕

```text
log/<YYYY-MM>/<flow_id>/prompts/<时间戳>_<role>_<sha12>_<req>.json      提示词
log/<YYYY-MM>/<flow_id>/prompts/<时间戳>_<role>_response_<sha12>.json   回复
```

提示词在调用**之前**写入：挂死、被杀、CLI 自己报错的那一次，恰恰最需要看提示词。
全部适配器都记录（Gemini 家族在 `_create_interaction`，Ollama 家族在 `_chat_json`）。
提示词内嵌资源内容，因此只落本地——`log/` 已在 `.gitignore` 中。`PROMPT_CACHE_ENABLED=false` 关闭。

## 13. 提示词：一个角色一个 YAML 文件，两部分

- 提示词正文全在 `config/prompts/<角色名>.yml`；`src/task_closed_loop/prompts/manifest.yml`
  只剩索引（角色、role 名、`includes` 共享段）。误删某个文件时回退到 manifest 旁的同名文件，
  两处都没有就报错并说清该放哪。
- 文件是 YAML，键分两组：
  - **给用户看的**：`说明`（这个角色干什么）、`变量`（它能用哪些 `{{变量名}}`、各是什么意思）。
    系统完全不读。
  - **给系统用的**：`设置`（`append_input` / `includes`）与 `提示词`（正文）。
    `PromptRegistry.template()` 返回的 `text` 就是 `提示词` 那一段。
  顶层键、`设置` 里的键都是白名单，写错当场报错——格式由 YAML 解析器保证，不靠分隔符约定。
- `llm/prompt_template.py` 负责替换：`VARIABLES` 是**系统固定提供的变量表**（中文名 + 英文别名 +
  它在本轮输入里的字段名），用户只是使用它们——`{{变量名}}` 写在正文哪里就替换在哪里，
  所以调整变量位置、增删段落就等于改提示词，替换不受影响。
- 第三~七步的正文都通过变量取输入，不再引用输入的 JSON 字段名。只有多形态角色
  （`task_discovery` 每一步输入不同）保留 `append_input: always`：每次都有的输入走变量，
  只有那一步才有的输入（findings / task_ideas 等）随【本轮输入】整份附上，正文里点名。
- 三个特殊变量：`{{输入}}`（本轮输入全文）、`{{引用语法}}`（共享段）、`{{角色}}`（角色名）。
- 失败即报错：变量名不存在、这个角色本轮没有这项输入、残留 `{{...}}`、文件名不是角色名、
  目录里混进 `.md`、顶层键或设置键不认识、`提示词` 缺失或不是文本，全部当场抛错，绝不插入空值。
- 装配点共 7 处（gemini / gemma / codex_cli / gemini_cli / ollama / openai_compatible / lmstudio），
  统一改为 `self._build_prompt(role_key, input_payload)` → `BuiltPrompt(text, include_input)`：
  正文用了输入变量时 `include_input=False`，Host 不再追加【本轮输入】，聊天式适配器也不再
  把输入单独发一遍。
- verify 脚本比对三件事：每个文件的 `变量` 清单 = 该角色真实的本轮输入；正文只用"每次都有"的
  变量（否则某些轮次会报错）；每一项输入都到得了模型（走变量或 `append_input: always`）。

## 14. 模型边界的可读命名

`model_io.py` 在送进模型前后翻译字段名：`INPUT_KEY_MAP`（单向，顶层段名）、
`FIELD_MAP`（双向，友好名全局唯一）、`OPAQUE_VALUE_KEYS`（值是用户/观察数据，不翻译）。
通用词（description、status、reason、user_value、reality_id…）故意不翻译：
它们在不同对象上含义不同，全局改名会串线。

引用语法统一在 `tasks/references.py`：`<type>:<identity>[#字段路径]`，
`#` 后用 `.键` / `[n]` 取值，必须真实存在，Host 逐级核对。

## 15. Secret Contract

Secret 唯一持久化位置：`cli_project/.env`。禁止把真实 Password / Token / API Key 写进系统环境变量或
子进程 `env`。配置与 Build Contract 只写引用；Host 只解析被声明的 key，并把值放进结构化执行输入，
不执行 `os.environ["..."] = secret`。

**CLI 的认证独立于本项目**：不向 CLI 子进程传递任何项目凭据，CLI 用它自己已登录的账号与配额。
CLI 本身工作在 `cli_project/`，`.env` 与它处于同一项目范围；当前架构不伪称已有 OS 级文件隔离——
要那种保证必须引入真实 Sandbox/权限层，并视为架构升级。

## 16. 执行闭环与结果可信度

7 Stage 只负责生产并审核任务。Accepted Task 之后才进入：

```text
Capability exists?
  yes -> execute
  no  -> CLI create/extend code -> test -> promote -> registry
                 ↓
              execute
                 ↓
        Host Verification / read-back
                 ↓
          TaskOutcomeRecord
```

进程退出码或 CLI 自己输出 `success` 只表示 process completed；只有通过 Verification Contract 的结果
才是可信 Outcome。

## 17. 回归验证

架构侧必须始终成立：Pipeline 只依赖 Contracts；7 Stage 顺序固定；Stage 7 → Stage 4；
Stage 1 三分支不混用；Stage 2 CLI `cwd=cli_project/`；Stage 3/4 是独立接口；架构锁仍以 1.2 加载。

实现侧必须始终守住：

- `payload` 嵌套 path/DSN/token 不得穿透任务边界；
- 本地资源不得用 CLI 自报观察代替 Host 重扫；
- 配置过的目录/功能不得静默遗漏（失败也要有条目）；
- 第二步在 `auto` 下不得重复初始化已有数据，在 `never` 下不得调用 CLI；
- 项目 id 在资源集合歧义时不得乱认旧项目；
- 功能到模型只有名字与身份，资源到第四/五步只有简介（`payload` 不进）；
- 任务的血缘必须来自本轮主题，没有血缘不得入库；
- 任务库写入被拒绝时必须回滚，且永不改动已存在库的结构；
- 提示词里的变量名必须存在且本轮确实有值，`{{变量名}}` 不得以字面量进入模型；
  提示词文件上半部分（功能说明 / 变量 / 变量说明 / 开关）不得进入模型，
  且各文件的变量表必须与适配器真实的本轮输入一致。
