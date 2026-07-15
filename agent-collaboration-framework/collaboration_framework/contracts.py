"""Framework-neutral Pydantic contracts shared by all components.

This module intentionally imports neither LangGraph nor a model provider.  The
same models validate JSON at the process boundary, node-to-node data, and LLM
structured output.
"""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator


class ContractError(ValueError):
    """Raised when a deterministic domain invariant is violated."""


class ContractModel(BaseModel):
    """Strict base model for every public JSON contract."""

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        str_strip_whitespace=True,
        validate_assignment=True,
    )

    def to_json_dict(self) -> dict[str, Any]:
        return json.loads(self.model_dump_json(by_alias=True))


# ---------------------------------------------------------------------------
# Module and rule-engine data. The module pipeline owns import validation; the
# atomic engine owns execution semantics. Pydantic validates shape, not
# authorization/transactions.


class Condition(ContractModel):
    path: str = Field(min_length=1)
    equals: JsonValue


class AllowOperation(ContractModel):
    op: Literal["allow"] = "allow"
    action: str = Field(min_length=1)


class ModifyOperation(ContractModel):
    op: Literal["modify"] = "modify"
    path: str = Field(min_length=1)
    set: JsonValue


Operation = Annotated[
    AllowOperation | ModifyOperation,
    Field(discriminator="op"),
]


class Rule(ContractModel):
    id: str = Field(min_length=1)
    hook: Literal["on_action", "on_scene_enter", "on_turn_end", "on_check_resolve"]
    priority: int = 0
    when: Condition
    then: list[Operation] = Field(default_factory=list)
    facts: list[str] = Field(default_factory=list)
    player_visible_information: list[str] = Field(default_factory=list)


class Scene(ContractModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    content: str
    entity_ids: list[str] = Field(default_factory=list)
    checkpoint_ids: list[str] = Field(default_factory=list)


class Entity(ContractModel):
    id: str = Field(min_length=1)
    kind: Literal["npc", "object", "location"]
    name: str = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)
    content: str
    secrets: str | None = None
    state: dict[str, JsonValue] = Field(default_factory=dict)
    refuse_ops: list[str] = Field(default_factory=list)
    blocked_text: str | None = None
    direct_responses: dict[str, str] = Field(default_factory=dict)
    rules: list[Rule] = Field(default_factory=list)


class CheckpointOutcome(ContractModel):
    facts: list[str] = Field(default_factory=list)
    player_visible_information: list[str] = Field(default_factory=list)
    narration_constraints: list[str] = Field(default_factory=list)
    ops: list[Operation] = Field(default_factory=list)


class CheckpointOutcomes(ContractModel):
    success: CheckpointOutcome
    failure: CheckpointOutcome


class Checkpoint(ContractModel):
    id: str = Field(min_length=1)
    scene_id: str = Field(min_length=1)
    action: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    skills: list[str] = Field(min_length=1)
    difficulty: Literal["regular", "hard", "extreme"]
    # Demo-only switch. The real engine replaces it with authoritative check data.
    mvp_check_result: Literal["success", "failure"] = "success"
    outcomes: CheckpointOutcomes


class WinCondition(ContractModel):
    id: str = Field(min_length=1)
    when: Condition
    fact: str
    player_visible_information: str


class ModuleContent(ContractModel):
    module_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    world_ref: str = Field(min_length=1)
    scenes: list[Scene]
    entities: list[Entity]
    checkpoints: list[Checkpoint]
    win_conditions: list[WinCondition]

    @model_validator(mode="after")
    def validate_references(self) -> ModuleContent:
        collections = {
            "Scene": [item.id for item in self.scenes],
            "Entity": [item.id for item in self.entities],
            "Checkpoint": [item.id for item in self.checkpoints],
            "WinCondition": [item.id for item in self.win_conditions],
        }
        for label, ids in collections.items():
            if len(ids) != len(set(ids)):
                raise ValueError(f"{label} id 必须唯一")

        scene_ids = set(collections["Scene"])
        entity_ids = set(collections["Entity"])
        checkpoint_ids = set(collections["Checkpoint"])
        scenes_by_id = {scene.id: scene for scene in self.scenes}

        for scene in self.scenes:
            if missing := set(scene.entity_ids) - entity_ids:
                raise ValueError(f"Scene {scene.id} 引用了不存在的 Entity: {sorted(missing)}")
            if missing := set(scene.checkpoint_ids) - checkpoint_ids:
                raise ValueError(
                    f"Scene {scene.id} 引用了不存在的 Checkpoint: {sorted(missing)}"
                )

        for checkpoint in self.checkpoints:
            if checkpoint.scene_id not in scene_ids:
                raise ValueError(f"Checkpoint {checkpoint.id} 的 Scene 不存在")
            if checkpoint.target_id not in entity_ids:
                raise ValueError(f"Checkpoint {checkpoint.id} 的 target 不存在")
            if checkpoint.id not in scenes_by_id[checkpoint.scene_id].checkpoint_ids:
                raise ValueError(
                    f"Checkpoint {checkpoint.id} 未列入 Scene {checkpoint.scene_id}"
                )

        known_paths = {
            f"entities.{entity.id}.{key}"
            for entity in self.entities
            for key in entity.state
        }
        for entity in self.entities:
            for rule in entity.rules:
                self._validate_condition(rule.when, known_paths, f"Rule {rule.id}")
                self._validate_operations(rule.then, known_paths, f"Rule {rule.id}")
        for checkpoint in self.checkpoints:
            self._validate_operations(
                checkpoint.outcomes.success.ops,
                known_paths,
                f"Checkpoint {checkpoint.id}.success",
            )
            self._validate_operations(
                checkpoint.outcomes.failure.ops,
                known_paths,
                f"Checkpoint {checkpoint.id}.failure",
            )
        for ending in self.win_conditions:
            self._validate_condition(ending.when, known_paths, f"WinCondition {ending.id}")
        return self

    @staticmethod
    def _validate_condition(condition: Condition, paths: set[str], owner: str) -> None:
        if condition.path not in paths:
            raise ValueError(f"{owner} 引用了不存在的状态路径 {condition.path}")

    @staticmethod
    def _validate_operations(
        operations: list[Operation], paths: set[str], owner: str
    ) -> None:
        for operation in operations:
            if isinstance(operation, ModifyOperation) and operation.path not in paths:
                raise ValueError(f"{owner} 写入了不存在的状态路径 {operation.path}")


class ActorState(ContractModel):
    player_id: str
    name: str


class GameState(ContractModel):
    """Authoritative state shape used by the fake engine, never graph state."""

    room_id: str
    scene_id: str
    phase: Literal["playing", "ended"] = "playing"
    ending_id: str | None = None
    event_sequence: int = Field(default=0, ge=0)
    actors: dict[str, ActorState]
    entities: dict[str, dict[str, JsonValue]]


# ---------------------------------------------------------------------------
# Per-turn contracts. These contain no LangGraph types.


class PlayerInput(ContractModel):
    room_id: str = Field(min_length=1)
    player_id: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    client_action_id: str = Field(min_length=1)
    utterance: str = Field(min_length=1)


class VisibleEntity(ContractModel):
    id: str
    kind: Literal["npc", "object", "location"]
    name: str
    aliases: list[str] = Field(default_factory=list)
    content: str
    # 由可信 ContextAssembler 明确放行；未列出的已匹配动作默认进入引擎。
    narrative_actions: list[str] = Field(default_factory=list)


class CheckpointOption(ContractModel):
    id: str
    action: str
    target_id: str
    skills: list[str] = Field(default_factory=list)


class TurnContext(ContractModel):
    scene_id: str
    phase: Literal["playing", "ended"]
    visible_entities: list[VisibleEntity] = Field(default_factory=list)
    checkpoint_options: list[CheckpointOption] = Field(default_factory=list)


class InterpretRequest(ContractModel):
    player_input: PlayerInput
    context: TurnContext


class MatchedTarget(ContractModel):
    matched: Literal[True] = True
    id: str = Field(min_length=1)


class UnmatchedTarget(ContractModel):
    matched: Literal[False] = False
    raw: str


IntentTarget = Annotated[
    MatchedTarget | UnmatchedTarget,
    Field(discriminator="matched"),
]


class NoCheck(ContractModel):
    route: Literal["none"] = "none"


class ModuleCheck(ContractModel):
    route: Literal["module"] = "module"
    checkpoint_id: str = Field(min_length=1)
    proposed_skills: list[str] = Field(default_factory=list)


class DefaultCheck(ContractModel):
    route: Literal["default"] = "default"
    proposed_skills: list[str] = Field(default_factory=list)


CheckProposal = Annotated[
    NoCheck | ModuleCheck | DefaultCheck,
    Field(discriminator="route"),
]


class Intent(ContractModel):
    execution: Literal["narrative", "engine"]
    kind: Literal["communicate", "interact", "unknown"]
    action: Literal["talk", "investigate", "open", "smash", "interact", "unknown"]
    target: IntentTarget
    check: CheckProposal
    narrative_intent: str
    clarification_question: str | None = None

    @model_validator(mode="after")
    def validate_routing_shape(self) -> Intent:
        unknown = self.kind == "unknown" or self.action == "unknown"
        if unknown:
            if self.execution != "narrative":
                raise ValueError("unknown Intent 只能进入 narrative 分支")
            if not isinstance(self.target, UnmatchedTarget):
                raise ValueError("unknown Intent 必须使用 unmatched target")
            if not isinstance(self.check, NoCheck):
                raise ValueError("unknown Intent 不能发起规则检定")
            if not self.clarification_question:
                raise ValueError("unknown Intent 必须提供 clarification_question")
        else:
            if not isinstance(self.target, MatchedTarget):
                raise ValueError("可执行 Intent 必须使用 matched target")
            if self.clarification_question is not None:
                raise ValueError("可执行 Intent 不得携带 clarification_question")
        if self.execution == "narrative" and not isinstance(self.check, NoCheck):
            raise ValueError("narrative 分支不能发起规则检定")
        return self


class EngineRequest(ContractModel):
    player_input: PlayerInput
    intent: Intent

    @model_validator(mode="after")
    def require_engine_route(self) -> EngineRequest:
        if self.intent.execution != "engine":
            raise ValueError("只有 execution=engine 才能组装 EngineRequest")
        return self


class StateChange(ContractModel):
    path: str
    from_value: JsonValue = Field(alias="from")
    to: JsonValue
    cause: str


class StateModifiedPayload(ContractModel):
    path: str = Field(min_length=1)
    from_value: JsonValue = Field(alias="from")
    to: JsonValue


class StateModifiedEvent(ContractModel):
    event_id: str
    sequence: int = Field(ge=1)
    type: Literal["state.modified"] = "state.modified"
    room_id: str
    actor_id: str
    client_action_id: str
    cause: str
    visibility: Literal["public", "private", "hidden"] = "public"
    payload: StateModifiedPayload


class ActionResult(ContractModel):
    success: bool
    resolution: Literal["checkpoint", "direct", "blocked", "unrecognized"]
    confirmed_facts: list[str] = Field(default_factory=list)
    player_visible_information: list[str] = Field(default_factory=list)
    state_changes: list[StateChange] = Field(default_factory=list)
    narration_constraints: list[str] = Field(default_factory=list)
    next_required_action: str | None = None
    events: list[StateModifiedEvent] = Field(default_factory=list)
    state_version: int = Field(default=0, ge=0)


class NarrationFact(ContractModel):
    """允许 Narrator 引用的一条玩家可见事实。"""

    id: str = Field(min_length=1)
    text: str = Field(min_length=1)


class PublicResultStatus(ContractModel):
    """Narrator 为组织语气所需的最小公开裁决状态。"""

    success: bool
    resolution: Literal["checkpoint", "direct", "blocked", "unrecognized"]


class NarrationRequest(ContractModel):
    """经过安全投影后才允许序列化给 Narrator 的输入。"""

    utterance: str = Field(min_length=1)
    context: TurnContext
    player_visible_facts: list[NarrationFact] = Field(default_factory=list)
    narration_constraints: list[str] = Field(default_factory=list)
    result_status: PublicResultStatus | None = None

    @model_validator(mode="after")
    def validate_safe_projection(self) -> NarrationRequest:
        fact_ids = [fact.id for fact in self.player_visible_facts]
        if len(fact_ids) != len(set(fact_ids)):
            raise ValueError("NarrationFact.id 必须唯一")
        return self


class NarrationOutput(ContractModel):
    kind: Literal["narration", "clarification"] = "narration"
    text: str = Field(min_length=1)
    claimed_fact_ids: list[str] = Field(default_factory=list)
    suggested_actions: list[str] = Field(default_factory=list)


class SummaryOperation(ContractModel):
    """Host-side outbox command for a non-authoritative conversation summary.

    A consumer may update only the summary store and must deduplicate by
    ``(room_id, client_action_id)``. It must never write GameState or EventLog.
    """

    op: Literal["append_turn_summary"] = "append_turn_summary"
    room_id: str
    client_action_id: str
    text: str
    source_event_ids: list[str] = Field(default_factory=list)


class TurnState(ContractModel):
    """Ephemeral LangGraph state for exactly one player input."""

    player_input: PlayerInput
    context: TurnContext | None = None
    intent: Intent | None = None
    action_result: ActionResult | None = None
    narration: NarrationOutput | None = None
    summary_op: SummaryOperation | None = None
    status: Literal["running", "clarification", "completed"] = "running"


class TurnOutput(ContractModel):
    """Host-internal turn result; never serialize this model to a player."""

    status: Literal["clarification", "completed"]
    player_input: PlayerInput
    intent: Intent
    action_result: ActionResult | None = None
    narration: NarrationOutput
    summary_op: SummaryOperation | None = None

    @classmethod
    def from_state(cls, state: TurnState) -> TurnOutput:
        if state.status == "running" or state.intent is None or state.narration is None:
            raise ContractError("LangGraph 回合尚未到达终态")
        return cls(
            status=state.status,
            player_input=state.player_input,
            intent=state.intent,
            action_result=state.action_result,
            narration=state.narration,
            summary_op=state.summary_op,
        )

    def to_player_output(self) -> NarrationOutput:
        """Project the only currently supported player-facing output."""

        return self.narration.model_copy(deep=True)
