"""`app/core/narrator.py` 单元测试（issue #107 地基）：

- `FallbackNarrator` 是确定性占位实现，验证不需要 mock 网络。
- `build_narrator` 按 `Settings.deepseek_api_key` 二选一。
- `DeepSeekNarrator` 的 prompt 组装（`_build_messages`）单独测——不发真实
  网络请求，只断言拼出来的 messages 里包含该有的信息。
"""

from app.core.config import Settings
from app.core.narrator import (
    DeepSeekNarrator,
    FallbackNarrator,
    NarrationContext,
    _build_messages,
    build_narrator,
)


async def test_fallback_narrator_returns_deterministic_placeholder_with_utterance() -> None:
    narrator = FallbackNarrator()
    context = NarrationContext(utterance="推开门", player_nickname="调查员A")

    text = await narrator.narrate(context)

    assert text == "守秘人记下了你的行动：「推开门」……"


def test_build_narrator_falls_back_without_api_key() -> None:
    settings = Settings(deepseek_api_key=None)

    assert isinstance(build_narrator(settings), FallbackNarrator)


def test_build_narrator_uses_deepseek_with_api_key() -> None:
    settings = Settings(deepseek_api_key="sk-test-key")

    assert isinstance(build_narrator(settings), DeepSeekNarrator)


def test_build_messages_includes_module_title_history_and_utterance() -> None:
    context = NarrationContext(
        utterance="检查桌上的信件",
        player_nickname="调查员A",
        module_title="尘封的手稿",
        recent_actions=["调查员B: 打开了门"],
    )

    messages = _build_messages(context)

    assert messages[0]["role"] == "system"
    user_content = messages[1]["content"]
    assert isinstance(user_content, str)
    assert "尘封的手稿" in user_content
    assert "调查员B: 打开了门" in user_content
    assert "调查员A：检查桌上的信件" in user_content


def test_build_messages_without_module_title_or_history() -> None:
    context = NarrationContext(utterance="环顾四周", player_nickname="调查员B")

    messages = _build_messages(context)

    user_content = messages[1]["content"]
    assert isinstance(user_content, str)
    assert user_content == "调查员B：环顾四周"
