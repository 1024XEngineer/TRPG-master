"""Confirm a model-resolved ordinary destination against the current step view."""

from collaboration_framework.contracts import (
    ActionAdjudication,
    ActionMethod,
    ActionPlanStep,
    ActionTarget,
    EnterLocationEffect,
    NarrativeOnlyEffect,
    NoAdjudicationCheck,
    PlayerView,
)


def satisfied_travel_adjudication(
    step: ActionPlanStep, view: PlayerView, proposal: ActionAdjudication
) -> ActionAdjudication | None:
    """Never discard a rule, check, failed route, or a non-travel side effect.

    A narrative-only location fallback with intent=location may mean an unknown
    destination. Only explicit self travel, or a travel confirmation with
    intent=none, establishes that this step is already satisfied.
    """
    if (
        step.kind != "travel"
        or proposal.method.family != "travel"
        or proposal.target.kind != "location"
        or proposal.target.id != view.scene.id
        or proposal.rule_decision is not None
        or not isinstance(proposal.check, NoAdjudicationCheck)
        or proposal.failure_effects
        or proposal.persistence_intent not in {"none", "location"}
    ):
        return None
    enters = False
    for effect in proposal.success_effects:
        if (
            isinstance(effect, EnterLocationEffect)
            and effect.location_id == view.scene.id
        ):
            enters = True
        elif not isinstance(effect, NarrativeOnlyEffect):
            return None
    if not enters and proposal.persistence_intent != "none":
        return None
    return proposal.model_copy(
        update={
            "summary": f"已经位于{view.scene.name}",
            "target": ActionTarget(kind="location", id=view.scene.id),
            "method": ActionMethod(
                family="action", description=f"确认当前已在{view.scene.name}"
            ),
            "persistence_intent": "none",
            "success_effects": (NarrativeOnlyEffect(),),
        },
        deep=True,
    )
