"""Player-safe, cross-turn context supplied to Host and Narrator models."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from collaboration_framework.contracts import (
    ActionOutcome,
    ActionResolution,
    ContractModel,
    PlayerInput,
    PlayerView,
    RuleCheckResult,
    VisibleFact,
)


HistoryVisibility = Literal["public", "player_scoped"]


class RecentHistoryBudget(ContractModel):
    """Deterministic limits used by a RecentHistorySource."""

    max_turns: int = Field(default=6, ge=1, le=24)
    max_chars: int = Field(default=6000, ge=2)


class VisibleHistoryText(ContractModel):
    """Text already visible to the current viewer at publication time."""

    text: str = Field(min_length=1)
    visibility: HistoryVisibility


class RecentSafeResult(ContractModel):
    """The deliberately small, player-safe projection of an ActionResult."""

    resolution: ActionResolution
    outcome: ActionOutcome
    check_result: RuleCheckResult | None = None
    visible_facts: tuple[VisibleFact, ...] = ()


class RecentTurn(ContractModel):
    """One prior action and only the evidence safe for the current viewer."""

    correlation_id: str = Field(min_length=1)
    source_player_id: str = Field(min_length=1)
    source_actor_id: str = Field(min_length=1)
    scene_id: str | None = Field(default=None, min_length=1)
    source_view_revision: str | None = Field(default=None, min_length=1)
    committed_view_revision: str | None = Field(default=None, min_length=1)
    participants: tuple[str, ...] = ()
    player_utterance: VisibleHistoryText
    accepted_intent_summary: str | None = Field(default=None, min_length=1)
    player_safe_result: RecentSafeResult | None = None
    published_narration: VisibleHistoryText | None = None
    evidence_refs: tuple[str, ...] = ()


class RecentTurnContext(ContractModel):
    """A revision-bound sequence of recent turns visible to one player."""

    room_id: str = Field(min_length=1)
    viewer_player_id: str = Field(min_length=1)
    as_of_revision: str = Field(min_length=1)
    turns: tuple[RecentTurn, ...] = ()

    @classmethod
    def empty(
        cls,
        *,
        player_input: PlayerInput,
        player_view: PlayerView,
    ) -> RecentTurnContext:
        return cls(
            room_id=player_input.room_id,
            viewer_player_id=player_input.player_id,
            as_of_revision=player_view.revision,
            turns=(),
        )

    def validate_for(
        self,
        *,
        player_input: PlayerInput,
        player_view: PlayerView,
    ) -> RecentTurnContext:
        if self.room_id != player_input.room_id or self.room_id != player_view.room_id:
            raise ValueError("RecentTurnContext room_id 与当前作用域不一致")
        if (
            self.viewer_player_id != player_input.player_id
            or self.viewer_player_id != player_view.player_id
        ):
            raise ValueError("RecentTurnContext viewer_player_id 与当前作用域不一致")
        if self.as_of_revision != player_view.revision:
            raise ValueError("RecentTurnContext as_of_revision 与 PlayerView 不一致")
        return self

    @model_validator(mode="after")
    def validate_visibility(self) -> RecentTurnContext:
        for turn in self.turns:
            own_turn = turn.source_player_id == self.viewer_player_id
            visible_texts = (turn.player_utterance, turn.published_narration)
            if (
                any(
                    text is not None and text.visibility == "player_scoped"
                    for text in visible_texts
                )
                and not own_turn
            ):
                raise ValueError("其他玩家的 player_scoped 历史不可见")
            if not own_turn and (
                turn.accepted_intent_summary is not None
                or turn.player_safe_result is not None
            ):
                raise ValueError("其他玩家的 Intent 或 ActionResult 不可见")
        return self
