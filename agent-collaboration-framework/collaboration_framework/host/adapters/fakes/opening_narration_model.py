"""Deterministic no-network opening model for tests and local development."""

from collaboration_framework.contracts import JsonObject
from collaboration_framework.host.application import deterministic_opening_narration
from collaboration_framework.host.schemas import OpeningNarrationContext


class FakeOpeningNarrationModel:
    async def generate(self, context: OpeningNarrationContext) -> JsonObject:
        return deterministic_opening_narration(context).to_json_dict()
