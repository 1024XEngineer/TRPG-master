from __future__ import annotations

import json
from typing import Literal

import anyio
import httpx
import pytest
from collaboration_framework.contracts import (
    PlayerView,
    SceneView,
    SelfActorView,
    VisibleActorView,
)
from collaboration_framework.engine import InMemoryEngineStore, RuleEngineService
from collaboration_framework.host.adapters.fakes import FakeIntentModel, FakeNarrationModel
from collaboration_framework.host.schemas import OpeningNarrationContext

from app.core.config import Settings
from app.core.turn import HostModelMetadata, build_turn_application


def opening_view() -> PlayerView:
    return PlayerView(
        room_id="room-1",
        player_id="player-1",
        actor_id="actor-1",
        background="1920 年代的阿卡姆，一行调查员受邀查看旧宅。",
        scene_id="foyer",
        phase="playing",
        revision="revision-1",
        self_actor=SelfActorView(
            id="actor-1",
            name="杜明",
            occupation="记者",
            background_summary="只允许在单人开场出现的背景。",
            public_status_summary="衣角沾着雨水。",
        ),
        scene=SceneView(
            id="foyer",
            name="旧宅门厅",
            description="昏黄灯光落在积灰的地板上。",
            visible_actors=(
                VisibleActorView(
                    id="actor-2",
                    name="林夏",
                    occupation="医生",
                    status_summary="提着急救箱。",
                ),
            ),
        ),
    )


class CandidateOpeningModel:
    def __init__(self, outcome: str) -> None:
        self.outcome = outcome
        self.calls = 0

    async def generate(self, context: OpeningNarrationContext):
        self.calls += 1
        if self.outcome == "timeout":
            await anyio.sleep(1)
        if self.outcome == "connection":
            raise httpx.ConnectError("connection failed")
        if self.outcome == "http":
            request = httpx.Request("POST", "https://provider.example/opening")
            response = httpx.Response(500, request=request)
            raise httpx.HTTPStatusError(
                "provider returned 500",
                request=request,
                response=response,
            )
        if self.outcome == "json":
            raise json.JSONDecodeError("invalid json", "{", 1)
        if self.outcome == "invalid-output":
            return {
                "kind": "clarification",
                "text": "杜明与林夏接下来做什么？",
                "claimed_fact_ids": [],
                "suggested_actions": [],
            }
        if self.outcome == "missing-participant":
            return {
                "kind": "narration",
                "text": "杜明站在旧宅门厅。",
                "claimed_fact_ids": [],
                "suggested_actions": [],
            }
        return {
            "kind": "narration",
            "text": "杜明与林夏一同站在旧宅门厅的昏黄灯光下。",
            "claimed_fact_ids": [],
            "suggested_actions": [],
        }


def application(
    model: CandidateOpeningModel,
    *,
    mode: Literal["model", "template"] = "model",
):
    store = InMemoryEngineStore()
    return build_turn_application(
        store,
        RuleEngineService(store),
        settings=Settings(
            opening_narration_mode=mode,
            opening_narration_timeout_seconds=0.01,
        ),
        intent_model=FakeIntentModel(),
        narration_model=FakeNarrationModel(),
        opening_narration_model=model,
        host_metadata=HostModelMetadata(provider="deepseek", model="deepseek-chat"),
    )


@pytest.mark.parametrize(
    ("outcome", "failure_category"),
    [
        ("timeout", "timeout"),
        ("connection", "connection"),
        ("http", "http_status"),
        ("json", "invalid_json"),
        ("invalid-output", "validation_opening_contract"),
        ("missing-participant", "validation_participant_coverage"),
    ],
)
async def test_opening_model_failures_use_player_safe_template(
    outcome: str,
    failure_category: str,
) -> None:
    result = await application(CandidateOpeningModel(outcome)).generate_opening(opening_view())

    assert result.result == "fallback"
    assert result.failure_category == failure_category
    for expected in ("旧宅门厅", "杜明", "记者", "林夏", "医生"):
        assert expected in result.narration.text
    assert "只允许在单人开场出现的背景" not in result.narration.text


async def test_valid_model_opening_mentions_every_public_participant() -> None:
    result = await application(CandidateOpeningModel("valid")).generate_opening(opening_view())

    assert result.result == "model"
    assert result.failure_category is None
    assert "杜明" in result.narration.text
    assert "林夏" in result.narration.text


async def test_template_mode_does_not_call_model() -> None:
    model = CandidateOpeningModel("valid")
    result = await application(model, mode="template").generate_opening(opening_view())

    assert result.result == "template"
    assert model.calls == 0
