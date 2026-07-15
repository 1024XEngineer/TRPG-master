"""Stateless-per-turn LangGraph orchestration.

LangGraph coordinates steps only. It owns neither game truth nor transaction
phases. The graph is deliberately compiled without a checkpointer for MVP.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Literal

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from .contracts import (
    ContractError,
    EngineRequest,
    InterpretRequest,
    NarrationOutput,
    NarrationRequest,
    PlayerInput,
    SummaryOperation,
    TurnOutput,
    TurnState,
)
from .ports import AtomicActionEngine, ContextAssembler, IntentInterpreter, Narrator

# TODO(orchestration): 节点必须保持为 ports 的薄包装。contracts/ports 禁止出现 LangGraph
# 类型；MVP 禁用 checkpointer。第二阶段若引入 interrupt，先评审并保证 checkpointer
# 只保存可丢弃的流程位置，不持有任何游戏事实的唯一副本。


@dataclass(frozen=True)
class GraphDependencies:
    context_assembler: ContextAssembler
    interpreter: IntentInterpreter
    engine: AtomicActionEngine
    narrator: Narrator


def _validated_update(state: TurnState, **updates: Any) -> dict[str, Any]:
    """Validate every node update with the same Pydantic state contract."""

    payload = state.model_dump(mode="python", by_alias=True)
    payload.update(updates)
    return TurnState.model_validate(payload).model_dump(mode="python", by_alias=True)


async def assemble_context_node(
    state: TurnState,
    runtime: Runtime[GraphDependencies],
) -> dict[str, Any]:
    context = await runtime.context.context_assembler.assemble_context(state.player_input)
    return _validated_update(state, context=context)


async def interpret_node(
    state: TurnState,
    runtime: Runtime[GraphDependencies],
) -> dict[str, Any]:
    if state.context is None:
        raise ContractError("interpret 前缺少 TurnContext")
    intent = await runtime.context.interpreter.interpret(
        InterpretRequest(player_input=state.player_input, context=state.context)
    )
    return _validated_update(state, intent=intent)


def route_after_interpret(
    state: TurnState,
) -> Literal["clarification", "engine_node", "narrate"]:
    if state.intent is None:
        raise ContractError("路由前缺少 Intent")
    if state.intent.clarification_question:
        return "clarification"
    if state.intent.execution == "narrative":
        return "narrate"
    return "engine_node"


async def clarification_node(state: TurnState) -> dict[str, Any]:
    if state.intent is None or not state.intent.clarification_question:
        raise ContractError("clarification 节点缺少澄清问题")
    return _validated_update(
        state,
        narration=NarrationOutput(
            kind="clarification",
            text=state.intent.clarification_question,
        ),
        status="clarification",
    )


async def engine_node(
    state: TurnState,
    runtime: Runtime[GraphDependencies],
) -> dict[str, Any]:
    if state.intent is None:
        raise ContractError("engine_node 前缺少 Intent")
    request = EngineRequest(player_input=state.player_input, intent=state.intent)

    # This is intentionally the node's only engine call. The production method
    # must keep rule validation + Event append + view update in one transaction.
    result = await runtime.context.engine.execute_action(request)
    return _validated_update(state, action_result=result)


async def refresh_context_node(
    state: TurnState,
    runtime: Runtime[GraphDependencies],
) -> dict[str, Any]:
    """Re-project the player-visible context after the engine commits."""

    if state.action_result is None:
        raise ContractError("refresh_context 前缺少 ActionResult")
    context = await runtime.context.context_assembler.assemble_context(state.player_input)
    return _validated_update(state, context=context)


async def narrate_node(
    state: TurnState,
    runtime: Runtime[GraphDependencies],
) -> dict[str, Any]:
    if state.context is None or state.intent is None:
        raise ContractError("narrate 前缺少 Context/Intent")
    narration = await runtime.context.narrator.narrate(
        NarrationRequest(
            player_input=state.player_input,
            context=state.context,
            intent=state.intent,
            action_result=state.action_result,
        )
    )
    return _validated_update(state, narration=narration)


async def prepare_summary_outbox_node(state: TurnState) -> dict[str, Any]:
    if state.narration is None:
        raise ContractError("prepare_summary_outbox 前缺少 NarrationOutput")
    events = state.action_result.events if state.action_result else []
    operation = SummaryOperation(
        room_id=state.player_input.room_id,
        client_action_id=state.player_input.client_action_id,
        text=state.narration.text,
        source_event_ids=[event.event_id for event in events],
    )
    return _validated_update(state, summary_op=operation, status="completed")


def build_turn_graph():
    builder = StateGraph(TurnState, context_schema=GraphDependencies)
    builder.add_node("assemble_context", assemble_context_node)
    builder.add_node("interpret", interpret_node)
    builder.add_node("clarification", clarification_node)
    builder.add_node("engine_node", engine_node)
    builder.add_node("refresh_context", refresh_context_node)
    builder.add_node("narrate", narrate_node)
    builder.add_node("prepare_summary_outbox", prepare_summary_outbox_node)

    builder.add_edge(START, "assemble_context")
    builder.add_edge("assemble_context", "interpret")
    builder.add_conditional_edges("interpret", route_after_interpret)
    builder.add_edge("clarification", END)
    builder.add_edge("engine_node", "refresh_context")
    builder.add_edge("refresh_context", "narrate")
    builder.add_edge("narrate", "prepare_summary_outbox")
    builder.add_edge("prepare_summary_outbox", END)

    # No checkpointer: every ainvoke is one disposable turn process.
    return builder.compile()


TURN_GRAPH = build_turn_graph()


async def run_turn(
    player_input: PlayerInput,
    dependencies: GraphDependencies,
) -> TurnOutput:
    raw_state = await TURN_GRAPH.ainvoke(
        TurnState(player_input=player_input),
        context=dependencies,
    )
    return TurnOutput.from_state(TurnState.model_validate(raw_state))


def run_turn_sync(
    player_input: PlayerInput,
    dependencies: GraphDependencies,
) -> TurnOutput:
    return asyncio.run(run_turn(player_input, dependencies))
