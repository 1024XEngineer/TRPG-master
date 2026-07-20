# LangGraph Ecosystem Tool Agent

这是一个与任何业务无关的 Agent 原理示例。它采用 LangChain 当前推荐的 `create_agent` 高层 API；该 API 的 Agent 循环运行在 LangGraph 上。工具通过 `@tool` 声明，框架负责生成 Schema、维护消息、执行工具并决定是否继续调用模型。

核心编排只有：

```python
def build_agent(model):
    return create_agent(model=model, tools=TOOLS, system_prompt=SYSTEM_PROMPT)
```

`LangGraphAgent.astream()` 的其余代码是教学展示层：把原生 `messages` 与 `updates` 流转换成可观察的文本增量、工具调用和工具结果，并不参与 Agent 决策。

## 项目边界

- 不导入主项目的任何包、类型、提示词或配置；
- 不导入另一个普通 Python 示例；
- 拥有独立的 `pyproject.toml`、源码、CLI 和测试；
- 使用 LangChain `create_agent`，不使用已弃用的 `langgraph.prebuilt.create_react_agent`。

## 通用工具

- `add_numbers(a, b)`：两个数相加；
- `get_current_time(timezone_name)`：读取指定 IANA 时区的当前时间。

## 运行

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/langgraph-tool-agent
.venv/bin/langgraph-tool-agent "What time is it in Asia/Shanghai? Use a tool."
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

测试使用假的 LangChain ChatModel，不消耗 API 配额：

```bash
.venv/bin/python -m unittest discover -s tests -v
```

建议先阅读 [`tools.py`](src/langgraph_tool_agent/tools.py) 和 [`agent.py`](src/langgraph_tool_agent/agent.py)，再与普通 Python 项目的显式循环对照。
