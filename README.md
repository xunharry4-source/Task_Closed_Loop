# Task Closed-Loop

主动发现并生成任务：分析你的工作目录与可用功能，自己归纳出项目，再按项目持续产出并审核任务。

当前发布版本：**V1.4｜六步流程**  
冻结架构版本：**Architecture Contract V1.2 / Architecture Locked**（本次没有改动架构）

## 六步流程

```text
第一步  用户配置
        工作目录（可多个，只写路径）、功能（可多个，只写名字）、用哪个 CLI
           ↓
第二步  CLI 自动生成分析代码（初始化数据，允许不执行）
        按资源 / 功能两个模版分析配置里的目录与功能，填好模版，保存到指定目录
           ↓
第三步  生成项目
        分析指定目录下的资源与功能，自己归纳出项目（不再由用户维护项目清单）
           ↓
第四步  问题 / 需求 / 价值 分别生成 → 生成主题
        三者互不读对方的结论；主题再按资源 + 功能 + 项目说明 + 这三层生成
           ↓
第五步  生成任务
        按项目的资源、功能、项目说明 + 主题，每个主题各一次调用
           ↓
第六步  审核任务
        按项目的资源、功能、项目说明独立审核
           ↓
        数量不足 → 补思考角度（当作新主题）→ 重新生成 → 再回第六步审核
```

六步落在冻结的 7 Stage 上，Pipeline 与 Contract 一行没动：

| 步骤 | 落点 |
|---|---|
| 一 用户配置 | `config/preflight_sources.yml` |
| 二 分析并填模版 | Stage 1（CLI 工作目录）+ Stage 2（分析与标准输出） |
| 三 生成项目 | Stage 2 之后、按项目起流水线之前（`implementations/composition.py`） |
| 四 问题/需求/价值 + 主题 | Stage 3 实现内（4 次调用） |
| 五 生成任务 | Stage 3 实现内（每个主题 1 次调用） |
| 六 审核任务 | Stage 4 |
| 数量不足 → 补角度 → 重生成 → 再审核 | Stage 5 / 6 / 7（Stage 7 的每个角度就是一个新主题） |

每个项目各跑一次完整流水线（候选被硬绑定在单一 `reality_id` 上）；
第二步的真实扫描全程只执行一次，按项目切分后分发。

## 第一步：你只配三件事

`config/preflight_sources.yml`：

```yaml
preflight_inputs:
  cli: codex          # codex（chatgpt）/ gemini / claude
  analyze: auto       # auto 没数据才跑 / always 全部重新初始化 / never 只用已保存的
  directories:        # 工作目录，可多个，只写路径
    - /Users/harry/Documents/trading_data
  functions:          # 功能，可多个，只写名字
    - codex
    - gmail
```

- 资源 id 由目录名得出（重名时用上层目录区分）；它是什么、现在有什么，由第二步的分析写进 `summary`。
- `cli` 一处决定第二步用哪个 CLI，同时作为第四~六步的推理适配器默认值；
  想让推理与分析用不同的东西时，再单独设 `TASK_LLM_ADAPTER` / `AUDIT_LLM_ADAPTER`。
  （`claude` 只能做第二步的分析，没有对应的推理适配器，会明确报错。）
- 需要凭据的功能：凭据只写在 `cli_project/.env`，配置文件里不出现。
- 另外两份配置：`config/task_store.yml`（任务库位置）、`config/task_generation.yml`（数量策略）；
  提示词在 `config/prompts/`，一个角色一个 `.yml`（见下节）。

## 第二步：初始化数据，可以不跑

第二步的作用是**初始化**：CLI 在长期工作目录 `cli_project/` 里写分析代码，Host 执行它，
把结果填进两个模版并保存。因此默认 `analyze: auto`——**指定目录里没有这一项的数据才跑，已经有了就跳过**；
新增一个目录或功能时，只初始化新增的那一项。

```text
cli_project/analysis/templates.py        两个模版（Host 拥有，CLI 不得修改）
cli_project/analysis/main.py             统一入口 + 手动触发（Host 拥有，CLI 不得修改）
cli_project/analysis/resources/<id>.py   CLI 写的资源分析：def analyze(target, context)
cli_project/analysis/functions/<名字>.py  CLI 写的功能分析：def analyze(target, context)
```

手动触发（入口强制实现，不依赖整条流程）：

```bash
python cli_project/analysis/main.py --list
python cli_project/analysis/main.py --directory /Users/harry/Documents/trading_data --write
python cli_project/analysis/main.py --all --write
```

`--write` 按 id 合并进标准输出，不会覆盖其它条目。缺少分析实现时入口返回
`availability: failed` 的条目，绝不静默漏掉已配置的输入。整批重新初始化：`PREFLIGHT_ANALYZE=always`。

### 两个模版

```yaml
# generated/resources.generated.yml
resources:
  - id: trading_data
    type: local_directory
    summary: 这是什么、现在有什么、到什么程度   # 后面每一步看到的"简介"就是它
    availability: available                  # available / unavailable / failed
    payload: {...}                           # 观察到的内容，结构自由
    metadata: {source_input_ids: [trading_data]}

# generated/capabilities.generated.yml
capabilities:
  - id: codex                                # = 功能名，一个功能一条，不按操作拆
    identity: OpenAI 的编码代理命令行工具       # 只写身份：谁开发的、什么类型的工具
    availability: available
    metadata: {source_function_id: codex}
```

保留的闸门：每个配置的目录与功能都必须出现（访问不了也要显式写 `unavailable` / `failed`）、
`availability` 合法、血缘 id 真实、`summary` 必填、本地目录由 Host 自己重扫、
`payload` 递归拒绝路径/URI/DSN/token（第二步 → 第四步的安全边界）。

产物与回执：

```text
cli_project/generated/resources.generated.yml
cli_project/generated/capabilities.generated.yml
cli_project/analysis/results/stage2.analysis.yml    Host 写的回执（不是 CLI 要填的模版）
cli_project/state/stage2_build_state.yml            哪一项已经初始化过
```

## 第三步：项目自己生成

把资源（id + summary）与功能名交给模型，输出项目列表：`name`、`description`（这个项目是干嘛的、
现在什么情况）、`resource_ids`。**一份资源可以同时属于多个项目**，数据允许共享；
资源是唯一的隔离边界，功能不分项目，所有项目共用。

项目 id 跨轮稳定：注册表 `cli_project/state/projects.yml`。沿用旧 id 的条件依次是——
模型给的 id 已在注册表里；或同名且至少共用一个资源；或资源集合**唯一**匹配某个旧项目。
都不满足就新建；消失的项目保留在注册表里不删。资源指纹没变时直接复用上一轮结果，不再提问。

（任务库里的任务/问题/价值/需求都挂 `entity_id`，去重与"已转任务"回写都靠它，id 一变历史就断。）

## 第四、五步：三层 → 主题 → 任务

```text
项目的资源(简介) + 功能(名字 + 身份) + 项目说明
        ├── 问题发现   未知盲区 / 已知缺陷
        ├── 价值发现   全新方案 / 增量方案
        └── 需求发现   突破型 / 基线型（现有功能覆盖不了的能力缺口）
                ↓   三者互不读对方的结论
            主题规划   优化·推进·收益·探针·破局（固定）+ 2–5 个推导主题
                ↓   每个主题各一次独立调用
              任务
```

- **任务只有三个基准**：资源、功能、主题。提示词里不附加别的限制——可行性、谁来做、
  价值大小、是否"合理"都不在生成期判断。第一遍以**数量与覆盖面**为目标，不做自我筛选，
  筛选是第六步的职责。唯一不放松的是**不得编造**：每条都必须有真实存在的依据引用。
- **功能只给名字与身份**：`{function: codex, identity: OpenAI 的编码代理命令行工具}`。
  **不给它能做什么**——不给操作清单、`target_scope`、`input_schema`。模型本来就认识这些工具，
  不认识的会自己去查；写死能力只会让它以为功能就只有那几项。任务写 `needed_functions`，
  Host 再映射回真实 capability id 交给第六步。
- **资源只给简介**：`resource_id` + 分析写的那句 `summary`。完整 `payload` 只进第六步的审核。
  因此提示词压到约 1000 字符/次。
- **主题带来源**：主题记录它覆盖了哪些问题/价值/需求；任务从主题继承血缘，
  Host 据此写 `source_table` / `source_id`。没有血缘的任务不入库。
- **没有现实层**：六步流程里不再有"构建现实"这一次调用。资源的 `summary` 已经是
  "现在有什么、到什么程度"，Host 直接确定性地拼出 `reality_id = <项目>-<周>`、
  `facts = {资源id: summary}`，用于填满契约 DTO 与 `reality_id` 一致性检查。

## 第六步：审核，以及数量不足时的补充

- 第六步按项目的资源（含完整 `payload`）、功能、项目说明独立审核，不与生成合并。
- 单条 LLM 审拆成两步：`task_candidate_destructive_audit`（核心是否成立）→
  通过后再跑 `task_candidate_field_audit`（字段要不要改写）；改写后只复检字段，不再重审核心。
- 只统计审核通过的业务任务；过少时生成思考角度，每个角度当作一个新主题重新问一次
  （同一角度只问一次），补出来的任务同样带项目与来源血缘，并且**全部回到第六步**再审一遍。
- 整条流水线结束后任务才写入任务库：同 `task_key` 的未结任务只 `times_proposed+1`，
  被搁置且未到期的跳过，命中 `exclusions` 的在生成期就丢弃，并回写来源 `status='已转任务'`。
  `task_key = sha256(entity_id, task_type, core_target)`。
  **对已存在的任务库只写数据，绝不改结构**；缺表直接报错并指出表名。

## 提示词：一个角色一个 YAML 文件

提示词全在 **[config/prompts/](config/prompts/)**，一个角色一个 `.yml`，文件名就是角色名
（`src/task_closed_loop/prompts/manifest.yml` 只剩索引：角色、role 名、共享段）。

**按步骤该改哪个文件、干什么用** → 见 **[config/prompts/README.md](config/prompts/README.md)**。

```yaml
角色: problem_discovery

# ---- 给用户看的：系统完全不读 ----
说明: |
  第四步：只看这一个项目，找它的问题（未知盲区 / 已知缺陷）。
变量:
  "{{项目}}": 这个项目：id、名称、一句话说明（英文别名 {{project}}）
  "{{资源}}": 本项目的资源：每条是 id + summary（英文别名 {{resources}}）
  "{{功能}}": 功能名 + identity，不含「能做什么」（英文别名 {{capabilities}}）
  "{{未结任务}}": 本项目还没结束的任务（英文别名 {{open_tasks}}）

# ---- 给系统用的：系统只读这两个 ----
设置:
  append_input: auto      # auto / always / never
  includes: true          # 是否保留共享段（引用语法）
提示词: |
  # 问题发现

  项目：

  {{项目}}

  它的资源（id + 简介：现在有什么、到什么程度）：

  {{资源}}

  只看这一个项目，两层都要找：…
```

**系统只读 `提示词` 与 `设置`**；`说明` / `变量` 是写给人看的，永远不进模型。

**变量由系统提供，你只管用**：变量名写死在代码里
（`src/task_closed_loop/llm/prompt_template.py` 的 `VARIABLES`），不能自造；
每个变量什么意思，就写在那个角色自己文件的 `变量:` 里——改哪个提示词，就在同一个文件里看到它能用什么。
**把 `{{变量名}}` 放到正文的哪个位置，本轮的真实内容就替换在那个位置**；调整位置、增删段落、改写措辞
都只是改提示词，替换照旧正确。

三条规则：

1. 变量值按类型插入：字符串原样，其它结构按 JSON（缩进 2）。
2. 变量名不存在、或这个角色本轮没有这项输入，**直接报错**并列出它实际有哪些——不会悄悄插空值。
3. 正文用了任何输入变量，Host 就不再追加【本轮输入】；用了 `{{引用语法}}` 也不再重复追加共享段。
   想强行改写 `append_input: always / never`，不要共享段写 `includes: false`。

三个特殊变量：`{{输入}}`（本轮输入全文）、`{{引用语法}}`（共享的引用语法段）、`{{角色}}`。
现在第三~七步的正文都已经用变量取输入，不再引用 JSON 字段名；只有 `task_discovery`
这种每一步输入都不同的旧角色，用 `append_input: always` 把本轮输入整份附在后面。
第二步的 `preflight_source_analysis` 整段交给 CLI，没有"本轮输入"，因此不支持变量（写了会报错）。

## 运行留痕

```text
log/<YYYY-MM>/<flow_id>/prompts/            每次模型调用的完整提示词与原始回复
log/<YYYY-MM>/<flow_id>/project_<id>.json   每个项目的链条全貌与入库统计
cli_project/generated[/<项目>]/rejections.round_N.yml   每轮各层被丢弃的原因
cli_project/generated[/<项目>]/tasks.*.yml  任务产物
任务库（默认参谋 SQLite）                    项目/问题/价值/需求/主题/任务 + 来源回写
```

提示词在调用**之前**写入：挂死、被杀、CLI 自己报错的那一次，恰恰最需要看提示词。
`PROMPT_CACHE_ENABLED=false` 可关闭；`log/` 已在 `.gitignore` 中。

## 架构冻结

```text
src/task_closed_loop/
├── pipeline/           # 冻结：7 Stage 顺序
├── contracts/          # 冻结：阶段接口 / DTO
├── implementations/    # 普通功能修改主要发生在这里
├── preflight/          # 第二步的分析、校验与标准输出
├── prompts/            # 只剩 manifest.yml（索引）；提示词正文在 config/prompts/*.yml
├── projects/           # 第三步：项目生成、id 注册表、按项目切分
├── llm/                # CLI / API / 模型底层
├── tasks/              # 任务领域能力
└── capability_runtime/ # CLI 与能力执行底层
```

正式 Pipeline 只依赖 `contracts/`；`app/runtime.py` 是 Composition Root，只负责选实现并注入。
普通修复默认只改 `implementations/` + Prompt + `preflight/` + `projects/` + `capability_runtime/cli/`。
只有明确进行架构升级时才允许动 `pipeline/`、核心 `contracts/` 和 `config/architecture_contract.yml`。

旧链条（发现 → 任务想法 → 候选任务，单一全局现实，含"构建现实"调用）仍保留在
`implementations/task_generation/llm.py`，用 `task_generation.first_step.mode: legacy_discovery` 切回。

## 模型与 CLI

推理（第三~七步）可以走本地 CLI，也可以走 API：

| 适配器 | 说明 |
|---|---|
| `codex_cli` / `gemini_cli` | 本地 CLI，用它自己已登录的账号与配额 |
| `openrouter` | 一个 key 走很多家模型的网关，**含 DeepSeek** |
| `deepseek` / `openai` | 厂商官方 API |
| `ollama` / `lmstudio` | 本地模型 |
| `gemini` / `gemma` | Google API |

走 OpenRouter 的 DeepSeek（`.env`，模型名必须带厂商前缀）：

```bash
OPENROUTER_API_KEY=sk-or-...
TASK_LLM_ADAPTER=openrouter
TASK_LLM_MODEL=deepseek/deepseek-v4.1-flash
AUDIT_LLM_ADAPTER=openrouter
AUDIT_LLM_MODEL=deepseek/deepseek-v4-pro
```

可选：`OPENROUTER_REASONING_EFFORT`（low/medium/high）、`OPENROUTER_TIMEOUT_SECONDS`（默认 300）、
`OPENROUTER_REFERER` / `OPENROUTER_TITLE`（OpenRouter 后台的来源署名）。
不单独设 `TASK_LLM_ADAPTER` 时，推理默认跟着第一步的 `preflight_inputs.cli` 走。

## CLI 支持

Codex CLI / Gemini CLI / Claude CLI。`--version` 只能证明已安装，不能证明可用；
READY 还必须通过非交互认证或健康探测（`MISSING / INSTALLED / NEEDS_AUTH / UNHEALTHY / READY`）。
默认按配置顺序选 READY 的 CLI，实际执行失败可继续 fallback；用户显式指定时不偷偷换。

安装、登录、账户授权由用户自己完成：本程序不装 CLI、不自动登录、不改全局凭据。
**CLI 的认证独立于本项目**：不向 CLI 子进程传递任何项目凭据。

## Secret

真实 Secret 只写入 `cli_project/.env`。**禁止**把 Password / Token / API Key 注入系统环境变量或
子进程环境变量；配置文件只写引用。Host 从 `.env` 读取被声明的 key，通过结构化执行输入交给代码，
不会 `os.environ[...] = secret`。输出代码、分析文件、标准输出文件都不得留下 Secret。

## 任务生产之后

```text
Accepted Task → 有能力吗？ → 缺能力时 CLI 在 cli_project/ 创建/扩展能力代码
→ Test / Promote / Registry → Execute → Host Verification / read-back → TaskOutcomeRecord
```

CLI 自己输出 `success/done` 不等于执行正确；可信结果由 Host Verification 决定。

## 启动

```bash
pip install -r requirements.txt
python start.py
```

只跑任务层（跳过第一、二步，读人工标准输入）：`config/task_inputs.yml` +
`config/task_layer_test/`。这是测试入口，不是正式生产旁路。

项目只维护 `README.md` 与 `ARCHITECTURE.md` 两份人工说明文档；Prompt `.md` 属于 Runtime 资产。
