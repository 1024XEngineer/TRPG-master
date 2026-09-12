"""Readable projections of existing public event fields; no module or model lookup."""

import json
from collections.abc import Mapping
from typing import Any


def payload_ids(payload: Mapping[str, Any], snake: str, camel: str) -> tuple[str, ...]:
    values = payload.get(snake, payload.get(camel, ()))
    if not isinstance(values, (list, tuple)):
        return ()
    return tuple(dict.fromkeys(value for value in values if isinstance(value, str) and value))


def event_text(event_type: str, payload: Mapping[str, Any]) -> str:
    """Keep authored text intact and render structured public check results."""
    for key in ("text", "utterance", "summary", "description", "content"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    if event_type == "check.result":
        skill = payload.get("skillName") or payload.get("skill_name") or payload.get("skill")
        roll = payload.get("rollValue", payload.get("roll_value"))
        target = payload.get("targetValue", payload.get("target_value"))
        outcome = (
            payload.get("successLevel") or payload.get("success_level") or payload.get("result")
        )
        if skill is not None and roll is not None and target is not None:
            name = payload.get("characterName") or payload.get("character_name") or "角色"
            return f"{name}进行{skill}检定：骰值 {roll}，目标值 {target}，结果 {outcome}。"
    return ""


def game_event_text(event_type: str, payload: Mapping[str, Any], actor_id: str) -> str:
    """Only materialize facts carried by recognized authoritative event types."""
    if text := event_text(event_type, payload):
        return text
    entity = payload.get("entity_id")
    if event_type == "entity.state_changed" and entity and payload.get("key"):
        key, value = payload["key"], payload.get("value")
        if key == "accompanying" and isinstance(value, bool):
            return f"{entity}{'开始' if value else '结束'}随{actor_id}同行。"
        return f"{entity}的{key}变为{json.dumps(value, ensure_ascii=False)}。"
    if event_type == "entity.moved" and entity:
        location, holder = payload.get("location_id"), payload.get("holder_actor_id")
        if payload.get("reason") == "accompanying" and location:
            return f"{entity}随{actor_id}一同抵达{location}。"
        if holder:
            return f"{entity}现在由{holder}持有。"
        if location:
            return f"{entity}被移到{location}。"
    if event_type in {"travel.resolved", "location.entered"}:
        destination = payload.get("destination_id") or payload.get("location_id")
        path = payload.get("path")
        origin = path[0] if isinstance(path, list) and path else None
        if destination:
            return f"{actor_id}{'从' + str(origin) if origin else ''}抵达{destination}。"
    if event_type in {"information.revealed", "information.hidden"}:
        info = payload.get("information_id")
        if info:
            verb = "获知" if event_type == "information.revealed" else "不再公开"
            return f"{actor_id}{verb}信息{info}。"
    if event_type == "entity.consumed" and entity:
        return f"{entity}已被消耗。"
    # Internal completion IDs and unknown payloads are not narrative experiences.
    return ""
