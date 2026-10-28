# analysis/

`main.py` 与 `templates.py` 由 Host 拥有，**不要修改**。它们提供统一入口与两个模版。

你（CLI 或人）只需要写分析实现：

```text
analysis/resources/<资源id>.py    def analyze(target, context) -> dict
analysis/functions/<功能名>.py     def analyze(target, context) -> dict
```

用 `templates.resource(...)` / `templates.capability(...)` 构造返回值。

手动触发：

```bash
python analysis/main.py --list
python analysis/main.py --directory /path/to/data --write
python analysis/main.py --function codex --write
```

缺少实现时入口会返回 `availability: failed` 的条目——已配置的输入永远不会被静默漏掉。
