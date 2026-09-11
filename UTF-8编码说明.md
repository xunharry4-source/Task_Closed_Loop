# UTF-8 编码说明

整个项目统一使用 UTF-8。

## 文件

Python、YAML、JSON、Markdown、TOML、TXT、环境配置等文本文件均使用 UTF-8。

`.editorconfig` 已固定：

```text
charset = utf-8
```

## Python 文本读写

项目文本读写显式声明：

```python
encoding="utf-8"
```

## Python 标准流

以下三个入口都会把 `stdin`、`stdout`、`stderr` 配置为 UTF-8：

```text
start.py
test_runtime.py
test.py
```

## 子进程

测试捕获子进程输出时固定：

```python
text=True
encoding="utf-8"
errors="replace"
```

不会依赖 Windows GBK / CP936。

## YAML / JSON

YAML 保留 Unicode 文本；JSON 保留 Unicode 字符。

同一项目在 Windows、Linux、macOS 使用相同文本编码语义。
