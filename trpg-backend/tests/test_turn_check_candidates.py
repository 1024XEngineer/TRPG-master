from collaboration_framework.contracts import (
    ActorResourceView,
    DefaultCheck,
    Intent,
    MatchedTarget,
    PlayerView,
    SceneView,
    SelfActorView,
)

from app.core.turn import TurnApplication


def test_luck_resource_is_available_to_default_check_selection() -> None:
    view = PlayerView(
        room_id="room",
        player_id="player",
        actor_id="actor",
        background="玩家可见背景。",
        scene_id="scene",
        phase="playing",
        revision="1",
        self_actor=SelfActorView(
            id="actor",
            name="调查员",
            resources=(
                ActorResourceView(id="luck", name="幸运", value=45),
                ActorResourceView(id="san", name="理智", value=60),
            ),
        ),
        scene=SceneView(
            id="scene",
            name="房间",
            description="一间普通房间。",
        ),
    )
    intent = Intent(
        kind="action",
        verb="search",
        target=MatchedTarget(id="scene"),
        check=DefaultCheck(proposed_skills=("luck",)),
        summary="碰碰运气搜索房间",
    )

    candidates, difficulty = TurnApplication._check_candidates(intent, view)

    assert [(item.id, item.name, item.target_value) for item in candidates] == [
        ("luck", "幸运", 45)
    ]
    assert difficulty == "regular"
