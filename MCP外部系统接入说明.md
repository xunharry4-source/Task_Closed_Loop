# MCP 外部系统接入说明

## 最重要的结论

正式接入 Gmail、数据库、服务器、第三方系统时，优先只修改：

```text
config/mcp_servers.yml
```

不需要为每个系统单独写 Python Adapter。

系统会自动做两类映射：

```text
MCP Resource
→ Task Closed-Loop Resource

MCP Tool
→ Task Closed-Loop Capability
```

---

# 一、安装 MCP Python SDK

使用你当前本地 Python 环境安装：

```bash
pip install "mcp>=2,<3"
```

项目不会自动安装。

---

# 二、添加 Streamable HTTP MCP Server

修改：

```text
config/mcp_servers.yml
```

例如：

```yaml
mcp:
  servers:

    company_system:
      enabled: true
      transport: streamable_http
      url: http://127.0.0.1:8000/mcp
```

保存后正常运行：

```text
start.py
```

系统会自动发现该 MCP Server 暴露的：

```text
resources
tools
```

---

# 三、添加 stdio MCP Server

例如：

```yaml
mcp:
  servers:

    gmail:
      enabled: true
      transport: stdio
      command: npx
      args:
        - -y
        - your-gmail-mcp-server
```

如果 MCP Server 需要环境变量：

```yaml
mcp:
  servers:

    gmail:
      enabled: true
      transport: stdio
      command: npx
      args:
        - -y
        - your-gmail-mcp-server

      env:
        GOOGLE_命令参数入口ENT_ID: ${GOOGLE_命令参数入口ENT_ID}
        GOOGLE_命令参数入口ENT_SECRET: ${GOOGLE_命令参数入口ENT_SECRET}
```

Secret 本体仍然放系统环境变量或你自己的 `.env`。

---

# 四、MCP Resource 会自动成为 Resource

假设 MCP Server 暴露：

```text
gmail://inbox
```

系统自动发现后，会将它转换为内部 Resource。

运行链：

```text
MCP resources/list
        ↓
ResourceDescriptor
        ↓
MCP resources/read
        ↓
ResourceSnapshot
        ↓
Reality Builder
```

用户不需要写转换代码。

---

# 五、MCP Tool 会自动成为 Capability

假设 MCP Server 暴露：

```text
send_email
```

系统自动转换成类似：

```text
Capability ID:
mcp.gmail.send_email

action_type:
send_email

description:
来自 MCP Tool 的 description

input_schema:
来自 MCP Tool 的 JSON Schema
```

因此 LLM 可以知道：

- 系统有什么功能
- 功能叫什么
- 功能说明
- 功能需要什么参数

真正执行时，Execution Runtime 会调用对应 MCP Tool。

---

# 六、只有 Tool，没有 Resource 的 MCP Server

有些 MCP Server 不提供 resources，只提供读取型 tools。

例如 Gmail Server 只提供：

```text
search_emails
```

这时可以把这个 Tool 声明成“Resource Tool”。

```yaml
mcp:
  servers:

    gmail:
      enabled: true
      transport: stdio
      command: npx
      args:
        - -y
        - your-gmail-mcp-server

      resource_tools:

        - id: recent_inbox
          tool: search_emails
          resource_type: gmail_messages

          arguments:
            query: newer_than:1d
```

系统每轮会：

```text
调用 search_emails
        ↓
获得结果
        ↓
转换为 Resource recent_inbox
        ↓
交给 Reality Builder
```

所以即使 MCP Server 自身没有 Resource primitive，也能直接用于 Reality。

---

# 七、多个 MCP Server

可以同时配置：

```yaml
mcp:
  servers:

    gmail:
      enabled: true
      transport: stdio
      command: ...

    database:
      enabled: true
      transport: streamable_http
      url: http://127.0.0.1:8100/mcp

    infrastructure:
      enabled: true
      transport: streamable_http
      url: http://127.0.0.1:8200/mcp
```

系统会把所有启用 Server 的 Resource / Capability 汇总到同一轮 Current Reality。

---

# 八、测试数据和真实系统是两条不同入口

## 测试

只改：

```text
config/test_resources.yml + config/test_capabilities.yml
```

运行：

```text
test_runtime.py
```

## 真实外部系统

只改：

```text
config/mcp_servers.yml
```

运行：

```text
start.py
```

---

# 九、什么时候才需要 Python Adapter

普通外部系统优先 MCP。

只有以下情况才考虑自定义 Adapter：

```text
目标系统没有 MCP Server
并且
无法用现有 MCP Server 包装
```

这属于高级扩展路径。

普通开发者无需接触。
