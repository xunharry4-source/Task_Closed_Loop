# 测试 Resource 与 Capability 配置说明

测试数据分成两个固定 YAML。

## Resource

文件：

```text
config/test_resources.yml
```

表示系统当前能看到的现实。

示例：

```yaml
resources:
  - id: server-01
    type: server_status
    fact: production server disk usage reached 95%
```

## Capability

文件：

```text
config/test_capabilities.yml
```

表示系统当前具备的能力。

示例：

```yaml
capabilities:
  - id: ticket.create
    description: create an incident ticket
    action_type: create_ticket
```

Capability 可以为空，用来测试当前存在现实问题、但系统没有可执行能力的情况。

## 测试入口

运行：

```text
test_runtime.py
```

它会同时读取两个测试 YAML，并调用真实 Gemini / Ollama。

## 正式入口

```text
start.py
```

正式入口不会启用这两个测试 YAML。
