import pytest
from pydantic import ValidationError

from app.core.host_entry import (
    HOST_ENTRY_FALLBACK,
    DeterministicHostEntryModel,
    HostDirectResponseSafetyPolicy,
    HostEntryContext,
    HostEntryDecision,
    HostEntryRouter,
    HostPublicContext,
    HostPublicContextProjector,
    HostPublicHistoryEntry,
    HostRuleCandidateContext,
    HostRuleMatchContext,
    HostRuleOptionContext,
)


def context(text: str = "跟邻居打个招呼") -> HostPublicContext:
    return HostPublicContext(
        public_scene="客厅",
        public_location="一楼",
        public_time="白天",
        visible_characters=("邻居",),
        visible_environment=("窗边有一张桌子",),
        recent_history=(
            HostPublicHistoryEntry(source="player_message", speaker="调查员", text="我走进客厅"),
        ),
        current_keeper_text=text,
    )


def test_route_text_contract_is_strict() -> None:
    assert HostEntryDecision(route="delegate_to_legacy").text is None
    assert HostEntryDecision(route="direct_response", text="点了点头").text == "点了点头"
    with pytest.raises(ValidationError):
        HostEntryDecision(route="direct_response")
    with pytest.raises(ValidationError):
        HostEntryDecision(route="delegate_to_legacy", text="不能带文本")
    with pytest.raises(ValidationError):
        HostEntryDecision(route="direct_response", text="x", extra_field="bad")
    rule = HostEntryDecision(route="rule_once", rule_id="r1", option_id="o1")
    assert rule.rule_id == "r1"
    with pytest.raises(ValidationError):
        HostEntryDecision(route="rule_once", rule_id="r1")
    with pytest.raises(ValidationError):
        HostEntryDecision(route="rule_once", rule_id="r1", option_id="o1", text="已成功")
    with pytest.raises(ValueError):
        HostDirectResponseSafetyPolicy().validate(
            HostEntryDecision(
                route="rule_once",
                rule_id="r1",
                option_id="o1",
                summary="搜索成功并获得线索",
            )
        )


def test_rule_match_context_is_allow_listed() -> None:
    context_value = HostEntryContext(
        public=context(),
        rule_match=HostRuleMatchContext(
            source_revision="rev-1",
            actor_id="actor-1",
            skills=("spot-hidden",),
            targets=(),
            rule_candidates=(
                HostRuleCandidateContext(
                    rule_id="rule-1",
                    question_kind="method",
                    options=(HostRuleOptionContext(id="option-1"),),
                ),
            ),
        ),
    )
    payload = context_value.to_model_payload()
    assert payload["rule_match"]["rule_candidates"][0]["rule_id"] == "rule-1"
    assert "content" not in str(payload)
    assert "private" not in str(payload)


@pytest.mark.parametrize(
    "text",
    ["检定成功，你获得了线索", "```json {} ```", "内部 revision=3", "时间将会改变"],
)
def test_safety_policy_rejects_authoritative_or_structured_text(text: str) -> None:
    with pytest.raises(ValueError):
        HostDirectResponseSafetyPolicy().validate(
            HostEntryDecision(route="direct_response", text=text)
        )


def test_safety_policy_allows_limited_immediate_reaction() -> None:
    decision = HostDirectResponseSafetyPolicy().validate(
        HostEntryDecision(route="direct_response", text="邻居礼貌地点了点头。")
    )
    assert decision.text == "邻居礼貌地点了点头。"


@pytest.mark.parametrize(
    "text",
    [
        "邻居因此信任你。",
        "邻居把案件线索告诉你。",
        "你成功说服了邻居。",
        "你发现了暗格里的钥匙。",
        "大家同意了这个计划，之后会照做。",
        "时间推进到夜晚，路线已经改变。",
    ],
)
def test_safety_policy_rejects_every_issue_authority_claim(text: str) -> None:
    with pytest.raises(ValueError):
        HostDirectResponseSafetyPolicy().validate(
            HostEntryDecision(route="direct_response", text=text)
        )


def test_projector_does_not_expose_ids_or_private_fields_and_bounds_history() -> None:
    class FakeView:
        pass

    view = FakeView()
    view.scene = type(
        "Scene",
        (),
        {
            "name": "客厅",
            "description": "明亮的房间",
            "time": "白天",
            "narrative_details": (),
            "visible_actors": (type("Actor", (), {"id": "actor-secret", "name": "邻居"})(),),
            "visible_entities": (),
        },
    )()
    view.location_context = None
    entries = [HostPublicHistoryEntry(source="player_message", text=f"消息{i}") for i in range(10)]
    projected = HostPublicContextProjector(max_turns=3, max_chars=8).project(
        view, current_keeper_text="你好", public_history=entries
    )
    payload = projected.to_model_payload()
    assert len(projected.recent_history) <= 3
    assert "actor-secret" not in str(payload)
    assert "private" not in str(payload)
    assert "revision" not in str(payload)


def test_public_history_accepts_direct_response_source() -> None:
    entry = HostPublicHistoryEntry(
        source="direct_response",
        speaker="主持人",
        text="邻居礼貌地点了点头。",
    )
    projected = HostPublicContextProjector(max_turns=3).project(
        type(
            "View",
            (),
            {
                "scene": type(
                    "Scene",
                    (),
                    {
                        "name": "客厅",
                        "description": "公开场景",
                        "time": "白天",
                        "narrative_details": (),
                        "visible_actors": (),
                        "visible_entities": (),
                    },
                )(),
                "location_context": None,
            },
        )(),
        current_keeper_text="你好",
        public_history=(entry,),
    )
    assert projected.recent_history[0].source == "direct_response"


@pytest.mark.asyncio
async def test_router_retries_once_then_uses_fixed_clarification() -> None:
    class BadModel:
        calls = 0

        async def generate(self, _context):
            self.calls += 1
            return {"route": "direct_response", "text": "检定成功"}

    model = BadModel()
    decision, provenance = await HostEntryRouter(model).decide(context())
    assert model.calls == 2
    assert decision.text == HOST_ENTRY_FALLBACK
    assert provenance == "fallback_clarification"


@pytest.mark.asyncio
async def test_router_retry_uses_the_same_public_context_and_never_delegates() -> None:
    class UnsafeThenUnsafeModel:
        def __init__(self) -> None:
            self.contexts = []

        async def generate(self, context):  # noqa: ANN001
            self.contexts.append(context)
            return {"route": "direct_response", "text": "你成功说服了邻居。"}

    model = UnsafeThenUnsafeModel()
    decision, _ = await HostEntryRouter(model).decide(context())
    assert decision.route == "direct_response"
    assert decision.text == HOST_ENTRY_FALLBACK
    assert len(model.contexts) == 2
    assert model.contexts[0] is model.contexts[1]


@pytest.mark.asyncio
async def test_force_legacy_is_router_decision_with_one_attempt() -> None:
    class ExplodingModel:
        async def generate(self, context):  # noqa: ANN001
            raise AssertionError("forced legacy must not call the model")

    router = HostEntryRouter(ExplodingModel(), force_legacy=True)
    decision, provenance = await router.decide(context())
    assert decision.route == "delegate_to_legacy"
    assert decision.text is None
    assert provenance == "forced_legacy"
    assert router.attempts == 1


@pytest.mark.asyncio
async def test_fake_router_delegates_complex_actions() -> None:
    router = HostEntryRouter(DeterministicHostEntryModel())
    decision, provenance = await router.decide(context("搜索书桌里的暗格"))
    assert decision.route == "delegate_to_legacy"
    assert decision.text is None
    assert provenance == "legacy_delegate"
