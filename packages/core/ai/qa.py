"""QAResponder —— 对应 master §4.5 + AI编排详细设计 §四。

纯只读、不推进剧情、不消耗回合，不产生 ActionResult——不复用 Narrator.narrate()
签名，硬塞会让人误解"QA 也会产生游戏效果"。协议专属入口 qa.ask，不经过
action.submit/IntentParser，天然不受回合门控。
"""

from __future__ import annotations

from typing import AsyncIterator, Protocol, runtime_checkable

from core.view.models import PlayerView


@runtime_checkable
class QAResponder(Protocol):
    def answer(self, question: str, view: PlayerView) -> AsyncIterator[str]:
        ...


class StubQAResponder:
    async def answer(self, question: str, view: PlayerView) -> AsyncIterator[str]:
        raise NotImplementedError("QAResponder.answer: 待接入 LLM（role='qa'）")
        yield ""  # pragma: no cover
