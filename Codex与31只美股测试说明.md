# Codex + 31 只最高市值美股测试

## 测试输入

Resource：

```text
config/test_resources.yml
```

包含截至 2026-08-29 的美国交易所上市股票市值前 31 名快照。

Capability：

```text
config/test_capabilities.yml
```

只提供：

```text
codex
```

Codex 能力描述为：

- 读取 / 写入代码
- 创建脚本
- 处理结构化数据
- 执行程序化分析
- 转换数据集
- 生成代码类工作产物

## 测试目的

验证系统是否会因为：

```text
有股票数据
+
有 Codex
```

就机械地产生任务。

正确边界：

> Resource 和 Capability 的存在本身不是 Task 触发器。

如果当前 Reality 只表达：

```text
这里有一份完整、当前、可用的前 31 名市值排行榜
```

而没有同时出现：

- 数据异常
- 数据缺失
- 当前冲突
- 已存在任务需要延续
- 执行结果产生的新现实
- 独立、当前且有价值的工作关系

那么：

```text
0 Task
```

是合法且重要的结果。

## 运行

先配置真实 Gemini 或 Ollama，然后：

```text
test_runtime.py
```

## 观察重点

重点检查生成结果是否出现以下错误倾向：

```text
“分析这 31 只股票”
“写一个脚本比较这些股票”
“生成排行榜”
“建立投资模型”
“寻找买入机会”
```

这些行为如果仅由“股票数据 + Codex”触发，属于 Resource / Capability 用途驱动，而不是 Reality 驱动。

如果模型识别不到独立现实工作关系，应返回：

```text
New Tasks: []
```
