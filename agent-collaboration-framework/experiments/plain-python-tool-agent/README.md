# Plain Python Tool Agent

这是一个与任何业务无关的 Agent 原理示例。它只使用 Python、OpenAI 兼容 SDK 和两个通用工具，完整手写以下循环：

1. 把用户消息和工具 JSON Schema 发给模型；
2. 在流式响应中拼接可能被拆分的工具名与 JSON 参数；
3. 执行本地工具并把结果作为 `tool` 消息加入上下文；
4. 再次调用模型，直到得到最终文本或触发轮数上限。

## 项目边界

- 不导入主项目的任何包、类型、提示词或配置；
- 不导入另一个 LangGraph 示例；
- 拥有独立的 `pyproject.toml`、源码、CLI 和测试；
- 唯一运行时依赖是 `openai`。

## 通用工具

- `add_numbers(a, b)`：两个数相加；
- `get_current_time(timezone_name)`：读取指定 IANA 时区的当前时间。

这些工具没有任何特定业务概念，适合单纯观察 Agent 的工具调用协议。

## 运行

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/plain-tool-agent
.venv/bin/plain-tool-agent "What time is it in Asia/Shanghai? Use a tool."
```

程序会向上查找最近的 `.env`，支持以下任一密钥名：

```dotenv
DASHSCOPE_API_KEY=...
# 或 QWEN_API_KEY=...
# 或 qwen_api_key=...
QWEN_MODEL=qwen-plus
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
```

## 测试

测试使用假的流式模型，不消耗 API 配额：

```bash
.venv/bin/python -m unittest discover -s tests -v
```

重点阅读 [`agent.py`](src/plain_python_tool_agent/agent.py)：工具参数分片合并、消息维护、工具异常回传与循环保护都是框架通常代为处理的工作。
