# Dependencies V0.2

## Core

- Python >= 3.11
- PyYAML >= 6.0, < 7

## Optional

### OpenAI adapter

- openai >= 1, < 3

### Generic HTTP adapter

- httpx >= 0.27, < 1

### Google adapters

- google-api-python-client >= 2, < 3
- google-auth >= 2, < 3
- google-auth-oauthlib >= 1, < 2

## Dev

- pytest >= 8, < 9

当前 V0.2 自带测试仍然使用标准库 `unittest`，因此 pytest 只是开发可选项。
