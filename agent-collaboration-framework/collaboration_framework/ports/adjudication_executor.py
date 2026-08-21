"""The only host command that may cause authoritative game-state effects."""

from typing import ClassVar, Protocol

from collaboration_framework.contracts import (
    AdjudicationExecution,
    CheckDecisionRequest,
    PostRollDecisionRequest,
    SubmitAdjudicationRequest,
)


class AdjudicationExecutor(Protocol):
    """v3's authoritative write boundary.

    This replaces the deleted `ActionExecutor` (#226). The shape changed with the
    runtime: v2 crossed the boundary once per action with an `ActionRequest` that
    the Checkpoint kernel resolved in one shot, while a v3 adjudication can pause
    on a check and resume through explicit player decisions — so the boundary is
    three calls rather than one.

    What did not change is why the Protocol exists: A must be able to depend on
    "there is exactly one way to change the world" without importing B's concrete
    service. Every implementation re-validates ids, revisions and request
    idempotency itself; naming a rule hands the outcome to that published rule
    (#226 §5), so a caller can never choose consequences directly.
    """

    # Keep a stable introspection surface for architecture checks across the
    # Python 3.11/3.12 Protocol implementations.
    __protocol_attrs__: ClassVar[tuple[str, ...]] = (
        "submit",
        "decide",
        "decide_post_roll",
    )

    async def submit(self, request: SubmitAdjudicationRequest) -> AdjudicationExecution: ...

    async def decide(self, request: CheckDecisionRequest) -> AdjudicationExecution: ...

    async def decide_post_roll(
        self,
        request: PostRollDecisionRequest,
    ) -> AdjudicationExecution: ...
