"""Stateless per-turn orchestration implemented with plain Python functions."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from .contracts import (
    ContractError,
    EngineRequest,
    InterpretRequest,
    ModuleCheck,
    NarrationFact,
    NarrationOutput,
    NarrationRequest,
    PlayerInput,
    PublicResultStatus,
    SummaryOperation,
    TurnOutput,
    TurnState,
)
from .ports import AtomicActionEngine, ContextAssembler, IntentInterpreter, Narrator
from .routing import harden_intent_routing


@dataclass(frozen=True)
class TurnDependencies:
    context_assembler: ContextAssembler
    interpreter: IntentInterpreter
    engine: AtomicActionEngine
    narrator: Narrator


def _updated_state(state: TurnState, **updates: Any) -> TurnState:
    """Validate every workflow update with the shared Pydantic contract."""

    payload = state.model_dump(mode="python", by_alias=True)
    payload.update(updates)
    return TurnState.model_validate(payload)


async def _assemble_context(
    state: TurnState,
    dependencies: TurnDependencies,
) -> TurnState:
    context = await dependencies.context_assembler.assemble_context(state.player_input)
    return _updated_state(state, context=context)


async def _interpret(
    state: TurnState,
    dependencies: TurnDependencies,
) -> TurnState:
    if state.context is None:
        raise ContractError("interpret 前缺少 TurnContext")
    proposed_intent = await dependencies.interpreter.interpret(
        InterpretRequest(player_input=state.player_input, context=state.context)
    )
    intent = harden_intent_routing(proposed_intent, state.context)
    return _updated_state(state, intent=intent)


def _clarify(state: TurnState) -> TurnState:
    if state.intent is None or not state.intent.clarification_question:
        raise ContractError("clarification 步骤缺少澄清问题")
    return _updated_state(
        state,
        narration=NarrationOutput(
            kind="clarification",
            text=state.intent.clarification_question,
        ),
        status="clarification",
    )


async def _execute_engine(
    state: TurnState,
    dependencies: TurnDependencies,
) -> TurnState:
    if state.intent is None:
        raise ContractError("engine 步骤前缺少 Intent")
    request = EngineRequest(player_input=state.player_input, intent=state.intent)

    # 原子引擎只调用一次；规则、Event、视图更新和事务不得拆到工作流中。
    result = await dependencies.engine.execute_action(request)
    return _updated_state(state, action_result=result)


async def _refresh_context(
    state: TurnState,
    dependencies: TurnDependencies,
) -> TurnState:
    """Re-project the player-visible context after the engine commits."""

    if state.action_result is None:
        raise ContractError("refresh_context 前缺少 ActionResult")
    context = await dependencies.context_assembler.assemble_context(state.player_input)
    return _updated_state(state, context=context)


def _stable_player_visible_fact_id(state: TurnState, index: int) -> str:
    """按裁决来源生成跨重试与幂等重放保持一致的玩家可见事实 ID。"""

    result = state.action_result
    if result is None:
        raise ContractError("生成玩家可见事实 ID 前缺少 ActionResult")
    if result.resolution == "checkpoint":
        if state.intent is None or not isinstance(state.intent.check, ModuleCheck):
            raise ContractError("Checkpoint 结果缺少对应 ModuleCheck")
        outcome = "success" if result.success else "failure"
        source = f"checkpoint:{state.intent.check.checkpoint_id}:{outcome}"
    else:
        source = f"action:{state.player_input.client_action_id}:{result.resolution}"
    return f"{source}:result:{index}"


def build_safe_narration_request(state: TurnState) -> NarrationRequest:
    """将内部回合状态投影为可以安全发送给 Narrator 的最小输入。"""

    if state.context is None or state.intent is None:
        raise ContractError("构造安全 NarrationRequest 前缺少 Context/Intent")
    if state.intent.execution == "engine" and state.action_result is None:
        raise ContractError("构造安全 NarrationRequest 前缺少 ActionResult")

    result = state.action_result
    player_visible_facts = [
        NarrationFact(
            id=_stable_player_visible_fact_id(state, index),
            text=text,
        )
        for index, text in enumerate(
            result.player_visible_information if result else [],
            start=1,
        )
    ]
    result_status = (
        PublicResultStatus(
            success=result.success,
            resolution=result.resolution,
        )
        if result
        else None
    )
    return NarrationRequest(
        utterance=state.player_input.utterance,
        context=state.context,
        player_visible_facts=player_visible_facts,
        narration_constraints=result.narration_constraints if result else [],
        result_status=result_status,
    )


async def _narrate(
    state: TurnState,
    dependencies: TurnDependencies,
) -> TurnState:
    if state.context is None or state.intent is None:
        raise ContractError("narrate 前缺少 Context/Intent")
    narration = await dependencies.narrator.narrate(
        build_safe_narration_request(state)
    )
    return _updated_state(state, narration=narration)


def _prepare_summary_outbox(state: TurnState) -> TurnState:
    if state.narration is None:
        raise ContractError("prepare_summary_outbox 前缺少 NarrationOutput")
    events = state.action_result.events if state.action_result else []
    operation = SummaryOperation(
        room_id=state.player_input.room_id,
        client_action_id=state.player_input.client_action_id,
        text=state.narration.text,
        source_event_ids=[event.event_id for event in events],
    )
    return _updated_state(state, summary_op=operation, status="completed")


async def run_turn(
    player_input: PlayerInput,
    dependencies: TurnDependencies,
) -> TurnOutput:
    """Execute one complete turn through an explicit Python call chain."""

    state = TurnState(player_input=player_input)
    state = await _assemble_context(state, dependencies)
    state = await _interpret(state, dependencies)

    if state.intent is None:
        raise ContractError("路由前缺少 Intent")
    if state.intent.clarification_question:
        return TurnOutput.from_state(_clarify(state))

    if state.intent.execution == "engine":
        state = await _execute_engine(state, dependencies)
        state = await _refresh_context(state, dependencies)

    state = await _narrate(state, dependencies)
    state = _prepare_summary_outbox(state)
    return TurnOutput.from_state(state)


def run_turn_sync(
    player_input: PlayerInput,
    dependencies: TurnDependencies,
) -> TurnOutput:
    return asyncio.run(run_turn(player_input, dependencies))
