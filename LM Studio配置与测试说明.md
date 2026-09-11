# LM Studio 配置与测试说明

## 支持方式

项目通过 LM Studio 的 OpenAI-compatible HTTP API 接入。

使用：

```text
GET  /v1/models
POST /v1/chat/completions
```

Task Closed-Loop 的结构化输出使用 LM Studio `response_format.type=json_schema`。

项目本身不会启动 LM Studio，也不会加载或下载模型。

---

## 1. 在 LM Studio 中启动 Local Server

在 LM Studio 的 Developer 页面启动 API Server。

项目默认连接：

```text
http://127.0.0.1:1234/v1
```

---

## 2. 配置

最少需要：

```env
LLM_ADAPTER=lmstudio
LLM_MODEL=<LM Studio 中的模型 id>
```

例如：

```env
LLM_ADAPTER=lmstudio
LLM_MODEL=openai/gpt-oss-20b
```

实际模型名以：

```text
GET http://127.0.0.1:1234/v1/models
```

返回的 `data[].id` 为准。

---

## 3. 可选配置

```env
LMSTUDIO_BASE_URL=http://127.0.0.1:1234/v1
LMSTUDIO_TIMEOUT_SECONDS=120
LMSTUDIO_MAX_TOKENS=
LMSTUDIO_API_KEY=
LLM_TEMPERATURE=0.0
```

通常本机无认证 Server 不需要 `LMSTUDIO_API_KEY`。

如果你的 LM Studio Server 开启了 Token/Auth，可填写该值，项目会发送：

```text
Authorization: Bearer <token>
```

---

## 4. 正式运行

```text
start.py
```

正式入口使用 MCP / 正式 Provider。

---

## 5. 测试 Resource / Capability

测试数据：

```text
config/test_resources.yml
config/test_capabilities.yml
```

运行：

```text
test_runtime.py
```

它会使用真实 LM Studio 模型执行完整：

```text
Resource + Capability
→ Reality
→ Task Discovery
→ Audit
→ Final Tasks
```

---

## 6. 启动检查

Runtime 启动时先请求：

```text
/v1/models
```

并确认：

```text
LLM_MODEL
```

存在于 `data[].id`。

模型不可见时会直接给出配置错误，并列出当前可见模型。

---

## 7. Structured Output

每个 Reality / Task Generation 角色都会通过：

```text
POST /v1/chat/completions
```

发送：

```text
response_format:
  type: json_schema
```

并把对应角色需要的 JSON Schema 交给 LM Studio。

这样 Reality、Candidate、Audit、Final Reality Review 继续使用与 Gemini / Ollama 相同的内部数据模型。

---

## 8. 当前自动测试范围

自动回归使用 Stub HTTP Transport，不连接真实 LM Studio。

已验证：

- 模型列表识别
- 缺失模型拒绝
- `/v1/chat/completions` 调用路径
- JSON Schema structured output
- JSON 结果解析
- LLM Factory 构造 LM Studio Adapter

真实模型的语义质量仍需要在本机运行：

```text
test_runtime.py
```
