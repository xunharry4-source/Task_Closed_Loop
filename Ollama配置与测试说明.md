# Ollama 配置与测试说明

## 一、正式 Runtime 现在必须配置 LLM

正式启动：

```bash
python start.py
```

不会再自动使用 FakeLLM 或 MockLLM。

至少需要：

```text
LLM_ADAPTER=ollama
LLM_MODEL=<你的本地 Ollama 模型名>
```

例如 Windows PowerShell：

```powershell
$env:LLM_ADAPTER="ollama"
$env:LLM_MODEL="qwen3:8b"
```

也可以写入你自己已有的 `.env`：

```env
LLM_ADAPTER=ollama
LLM_MODEL=qwen3:8b
```

项目不会创建或改写 `.env`。

---

## 二、Ollama 地址

默认：

```text
http://127.0.0.1:11434
```

需要修改时：

```powershell
$env:OLLAMA_BASE_URL="http://127.0.0.1:11434"
```

或者：

```env
OLLAMA_BASE_URL=http://127.0.0.1:11434
```

其他可选配置：

```env
OLLAMA_TIMEOUT_SECONDS=120
OLLAMA_KEEP_ALIVE=5m
OLLAMA_THINK=false
LLM_TEMPERATURE=0.0
```

---

## 三、确认模型名

先在本机运行：

```bash
ollama list
```

把实际模型名填写到：

```text
LLM_MODEL
```

例如：

```env
LLM_MODEL=qwen3:8b
```

正式启动时程序会访问 Ollama 的模型列表。

配置的模型不存在时，启动直接失败，并显示当前 Ollama 返回的可用模型。

---

## 四、只配置 Ollama 仍然不能启动

Task Closed-Loop 还需要 Resource / Capability Provider。

因此只配置：

```env
LLM_ADAPTER=ollama
LLM_MODEL=qwen3:8b
```

而没有任何 Provider 时，会明确报错：

```text
没有启用任何 Resource / Capability Provider
```

这是正常行为。

---

## 五、用真实 Ollama 测 Resource / Capability

修改：

```text
config/test_resources.yml + config/test_capabilities.yml
```

然后：

```powershell
.
un_test.py
```

程序会使用真实 Ollama，并读取这个固定 YAML 文件。


## 六、测试数据来源

测试数据只来自：

```text
config/test_resources.yml + config/test_capabilities.yml
```

修改这个文件即可改变 Resource / Capability。


## 七、真正接入你的 Resource / Capability

关闭 固定测试配置：

```powershell
$env:="false"
```

然后在：

```text
config/providers.yml
```

显式启用你的真实 Provider。

具体见：

```text
资源与能力扩展说明.md
开发扩展速查.md
```

---

## 八、不配置 LLM 时

直接：

```powershell
python start.py
```

预期启动失败。

例如：

```text
[CONFIG ERROR] LLM 未配置：请设置 LLM_ADAPTER。当前支持：ollama。
```

这代表正式 Runtime 没有再偷偷使用测试 LLM。

---

## 九、配置模型但 Ollama 没启动

会出现类似：

```text
[CONFIG ERROR] 无法连接 Ollama：http://127.0.0.1:11434/...
```

程序停止。

---

## 十、模型名错误

例如：

```env
LLM_MODEL=not-installed-model
```

启动会失败并提示：

```text
Ollama 模型未找到
```

同时列出 Ollama 返回的已安装模型。

---

## 十一、自动测试

运行：

```powershell
python test.py
```

或者：

```bash
python test.py
```

自动测试使用：

```text
tests/support/reasoners.py
```

里的测试替身。

这些测试替身不属于正式 Runtime。

正式目录：

```text
src/task_closed_loop/llm/
```

只保留：

```text
ollama.py
factory.py
ports.py
prompt_registry.py
```

---

## 十二、推荐的第一次真实 Ollama 测试

PowerShell：

```powershell
cd C:\git\Task_Closed_Loop_Python

ollama list

$env:LLM_ADAPTER="ollama"
$env:LLM_MODEL="你在 ollama list 里看到的模型名"
$env:="true"
$env:config/test_resources.yml + config/test_capabilities.yml="one_task"

python start.py
```

确认这个场景通过后，再测试：

```powershell
$env:config/test_resources.yml + config/test_capabilities.yml="zero_task"
python start.py

$env:config/test_resources.yml + config/test_capabilities.yml="multi_task"
python start.py
```

这三个场景最适合先验证真实 LLM Prompt。
