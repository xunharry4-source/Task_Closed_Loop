# Gemini 配置与测试说明

## 一、安装

使用你本地已经安装好的 Python 环境。

Gemini SDK：

```bash
pip install -U google-genai
```

项目不会自动安装。

---

## 二、正式 LLM 配置

至少设置：

```env
LLM_ADAPTER=gemini
LLM_MODEL=gemini-3.6-flash
GEMINI_API_KEY=<你的 API Key>
```

Google Gen AI SDK 也支持：

```env
GOOGLE_API_KEY=<你的 API Key>
```

如果两个都存在，由 Google SDK 自己处理优先级。

---

## 三、项目使用的 Gemini 调用方式

项目使用：

```python
from google import genai

client = genai.Client()

interaction = client.interactions.create(
    model=...,
    input=...,
    response_format=...,
)

text = interaction.output_text
```

也就是 Google Gen AI SDK 的 Interactions API。

不是旧的 `generate_content` 调用链。

---

## 四、Prompt 如何进入 Gemini

每一个 LLM 职责都有独立 Prompt：

```text
reality_builder.md
existing_task_continuity.md
task_discovery.md
task_candidate_destructive_audit.md
task_candidate_set_audit.md
task_reality_validity.md
```

运行时：

```text
Prompt
+
本轮结构化输入
+
JSON response_format
        ↓
client.interactions.create(...)
```

Gemini 返回：

```text
interaction.output_text
```

项目再解析成对应 Python Model。

---

## 五、第一次真实 Gemini 测试

配置 LLM：

```powershell
$env:LLM_ADAPTER="gemini"
$env:LLM_MODEL="gemini-3.6-flash"
$env:GEMINI_API_KEY="你的Key"
```

修改：

```text
config/test_resources.yml + config/test_capabilities.yml
```

然后：

```powershell
.
un_test.py
```

测试数据完全来自这个 YAML 文件。


## 六、测试其他 Resource / Capability

继续修改：

```text
config/test_resources.yml + config/test_capabilities.yml
```

再运行：

```powershell
.
un_test.py
```

不需要 Scenario。


## 七、没有配置 LLM

直接：

```powershell
python start.py
```

会失败并提示：

```text
LLM 未配置：请设置 LLM_ADAPTER
```

程序不会再自动选择 FakeLLM。

---

## 八、没有 API Key

已经设置：

```text
LLM_ADAPTER=gemini
LLM_MODEL=...
```

但没有：

```text
GEMINI_API_KEY
GOOGLE_API_KEY
```

启动会失败并明确提示 Gemini API Key 未配置。

---

## 九、没有 Provider

Gemini 已配置，但是没有启用任何 Resource / Capability Provider 时，启动也会失败。

如果只是测试提示词，显式设置：

```env
=true
config/test_resources.yml + config/test_capabilities.yml=one_task
```

如果正式运行，则在：

```text
config/providers.yml
```

配置真实 Provider。

---

## 十、Fake 数据不会自动出现

`FakeScenarioProvider` 默认关闭。

即使：

```env
=true
```

还必须显式指定：

```env
config/test_resources.yml + config/test_capabilities.yml=one_task
```

否则启动失败。

所以正式启动不会再无配置自动出现：

```text
production certificate expires tomorrow
```

---

## 十一、自动回归测试

```powershell
python test.py
```

或者：

```bash
python test.py
```

自动回归不调用真实 Gemini API。

Gemini Adapter 使用注入的 Stub Client 验证：

```text
client.interactions.create
model
input
response_format
interaction.output_text
JSON parsing
```

真实 API 联调由 `start.py` + 你的 Gemini 配置完成。
