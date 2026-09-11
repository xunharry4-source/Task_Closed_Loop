# Configuration

配置分为两层：

1. YAML：结构、路径、非敏感默认值。
2. Environment：实际运行值与敏感信息。

本地 Environment 通过 `.env` 加载。

YAML 支持 `${ENV_NAME:default}`，例如：

```yaml
llm:
  adapter: ${LLM_ADAPTER:fake}
```

Secret 通过 `get_secret()` 从环境变量读取。
