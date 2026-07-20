# Agent Orchestration Examples

这里包含两个业务无关、可分别复制和运行的 Agent 教学项目：

| 项目 | 编排方式 | 直接运行时依赖 |
| --- | --- | --- |
| [`plain-python-tool-agent`](plain-python-tool-agent/) | 手写模型—工具—模型循环 | `openai` |
| [`langgraph-tool-agent`](langgraph-tool-agent/) | LangChain `create_agent`，LangGraph 运行时 | `langchain`、`langchain-openai`、`langgraph` |

二者使用相同的通用提示词意图和工具语义，但没有共享 Python 包、共享配置模块或交叉导入。每个目录都有自己的 `pyproject.toml`、源码、CLI、README 和测试，应在各自虚拟环境中安装。

比较结论与测量方法见 [`agent-orchestration-evaluation/COMPLEXITY_REPORT.md`](agent-orchestration-evaluation/COMPLEXITY_REPORT.md)，基于实验的三层技术选型补充见 [`../docs/agent编排技术选型.md`](../docs/agent编排技术选型.md)。评估目录只保存研究文档，不提供任何被两个示例导入的运行时代码。
