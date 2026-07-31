"""后端对外部端口的基础设施 Adapter。"""

from app.adapters.deepseek_models import DeepSeekChatCompletionsJsonClient
from app.adapters.openai_models import (
    OpenAIResponsesJsonClient,
    PromptIntentModel,
    PromptNarrationModel,
    PromptOpeningNarrationModel,
)
from app.adapters.qwen_models import QwenChatCompletionsJsonClient
from app.adapters.sqlalchemy_engine_store import SqlAlchemyEngineStore
from app.adapters.sqlalchemy_recent_history import SqlAlchemyRecentHistorySource

__all__ = [
    "OpenAIResponsesJsonClient",
    "DeepSeekChatCompletionsJsonClient",
    "PromptIntentModel",
    "PromptNarrationModel",
    "PromptOpeningNarrationModel",
    "QwenChatCompletionsJsonClient",
    "SqlAlchemyEngineStore",
    "SqlAlchemyRecentHistorySource",
]
