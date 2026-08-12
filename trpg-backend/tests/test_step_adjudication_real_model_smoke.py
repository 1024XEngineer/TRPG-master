"""按需使用真实 DeepSeek 验证步骤裁决成功路径与传输错误分类。"""

from __future__ import annotations

import os

import pytest
from collaboration_framework.contracts import (
    ActionPlanStep,
    PlayerInput,
    PlayerView,
    SceneView,
    SelfActorView,
)
from collaboration_framework.host.application import TurnExecutionError
from collaboration_framework.host.schemas import ActionPlanStepContext

from app.adapters.deepseek_models import DeepSeekChatCompletionsJsonClient
from app.adapters.openai_models import PromptActionPlanStepAdjudicator
from app.adapters.structured_http import ModelClientRetryPolicy
from app.core.config import Settings, secret_value

RUN_REAL_SMOKE = os.getenv("RUN_DEEPSEEK_STEP_FAILURE_SMOKE") == "1"


def _context() -> ActionPlanStepContext:
    """构造不含模组秘密的最小步骤上下文，避免真实烟测泄露测试数据。"""

    player_input = PlayerInput(
        room_id="deepseek-step-smoke-room",
        player_id="deepseek-step-smoke-player",
        actor_id="deepseek-step-smoke-actor",
        client_action_id="deepseek-step-smoke-action",
        utterance="观察当前房间",
    )
    return ActionPlanStepContext(
        player_input=player_input,
        plan_id="deepseek-step-smoke-plan",
        plan_goal="观察当前房间",
        step_index=0,
        step_request_id="deepseek-step-smoke-action-step-0",
        step=ActionPlanStep(kind="action", semantic_goal="观察当前房间"),
        player_view=PlayerView(
            room_id=player_input.room_id,
            player_id=player_input.player_id,
            actor_id=player_input.actor_id,
            background="调查员正在一间安静的测试房间中。",
            scene_id="deepseek-step-smoke-scene",
            phase="playing",
            revision="0",
            self_actor=SelfActorView(id=player_input.actor_id, name="调查员"),
            scene=SceneView(
                id="deepseek-step-smoke-scene",
                name="测试房间",
                description="房间内没有可见人物或物品。",
            ),
        ),
    )


def _adjudicator(settings: Settings, *, timeout_seconds: float) -> PromptActionPlanStepAdjudicator:
    """每个烟测只允许一次 HTTP 尝试，确保总调用次数不会因重试翻倍。"""

    assert settings.deepseek_api_key is not None
    client = DeepSeekChatCompletionsJsonClient(
        api_key=secret_value(settings.deepseek_api_key),
        base_url=settings.deepseek_base_url,
        model=settings.deepseek_model,
        timeout_seconds=timeout_seconds,
        retry_policy=ModelClientRetryPolicy(max_attempts=1, backoff_seconds=0),
    )
    return PromptActionPlanStepAdjudicator(client)


@pytest.mark.skipif(
    not RUN_REAL_SMOKE,
    reason="设置 RUN_DEEPSEEK_STEP_FAILURE_SMOKE=1 后才执行真实 DeepSeek 烟测",
)
async def test_real_deepseek_step_adjudication_succeeds() -> None:
    settings = Settings()
    result = await _adjudicator(
        settings,
        timeout_seconds=settings.deepseek_timeout_seconds,
    ).adjudicate(_context())

    assert result.summary
    assert result.target.id == "deepseek-step-smoke-scene"


@pytest.mark.skipif(
    not RUN_REAL_SMOKE,
    reason="设置 RUN_DEEPSEEK_STEP_FAILURE_SMOKE=1 后才执行真实 DeepSeek 烟测",
)
async def test_real_deepseek_timeout_is_classified() -> None:
    settings = Settings()
    adjudicator = _adjudicator(settings, timeout_seconds=0.001)

    with pytest.raises(TurnExecutionError) as caught:
        await adjudicator.adjudicate(_context())

    assert caught.value.code == "MODEL_UPSTREAM_UNAVAILABLE"
    assert caught.value.retryable is True
