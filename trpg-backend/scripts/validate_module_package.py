#!/usr/bin/env python3
"""Validate a runtime-ready ModulePackage fixture with the standard library."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REQUIRED_TOP_LEVEL = {
    "package_schema_version",
    "package_id",
    "package_status",
    "source_manifest",
    "module",
    "keeper_brief",
    "runtime_defaults",
    "content",
    "initial_state",
    "assets",
    "normalization_decisions",
    "validation",
}

CONTENT_COLLECTIONS = (
    "facts",
    "scenes",
    "entities",
    "clues",
    "checkpoints",
    "sanity_events",
    "triggers",
    "endings",
)

SINGLE_REFERENCE_FIELDS = {
    "scene_id": "scenes",
    "entity_id": "entities",
    "clue_id": "clues",
    "checkpoint_id": "checkpoints",
    "sanity_event_id": "sanity_events",
    "trigger_id": "triggers",
    "ending_id": "endings",
}

MULTI_REFERENCE_FIELDS = {
    "next_scene_ids": "scenes",
    "entity_ids": "entities",
    "clue_ids": "clues",
    "checkpoint_ids": "checkpoints",
    "trigger_ids": "triggers",
    "knowledge_fact_ids": "facts",
    "knowledge_clue_ids": "clues",
    "reveals_fact_ids": "facts",
    "must_not_reveal_before_granted": "facts",
}


def walk(value: Any, path: str = "$"):
    yield path, value
    if isinstance(value, dict):
        for key, child in value.items():
            yield from walk(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from walk(child, f"{path}[{index}]")


def detect_trigger_cycles(triggers: list[dict[str, Any]]) -> list[str]:
    graph = {trigger["id"]: set() for trigger in triggers}
    for trigger in triggers:
        for _, value in walk(trigger.get("effects", [])):
            if isinstance(value, dict) and value.get("type") == "fire_trigger":
                target = value.get("trigger_id")
                if isinstance(target, str):
                    graph[trigger["id"]].add(target)

    visiting: set[str] = set()
    visited: set[str] = set()
    cycles: list[str] = []

    def visit(node: str, chain: list[str]) -> None:
        if node in visiting:
            start = chain.index(node)
            cycles.append(" -> ".join(chain[start:] + [node]))
            return
        if node in visited:
            return

        visiting.add(node)
        for target in graph.get(node, set()):
            visit(target, chain + [target])
        visiting.remove(node)
        visited.add(node)

    for trigger_id in graph:
        visit(trigger_id, [trigger_id])
    return cycles


def validate(package: dict[str, Any]) -> list[str]:
    errors: list[str] = []

    missing = REQUIRED_TOP_LEVEL - package.keys()
    if missing:
        errors.append(f"missing top-level fields: {sorted(missing)}")

    if package.get("package_status") != "ready":
        errors.append("package_status must be 'ready'")

    content = package.get("content")
    if not isinstance(content, dict):
        return errors + ["content must be an object"]

    indexes: dict[str, set[str]] = {}
    all_ids: dict[str, str] = {}
    for collection_name in CONTENT_COLLECTIONS:
        collection = content.get(collection_name)
        if not isinstance(collection, list):
            errors.append(f"content.{collection_name} must be an array")
            indexes[collection_name] = set()
            continue

        indexes[collection_name] = set()
        for index, item in enumerate(collection):
            item_path = f"content.{collection_name}[{index}]"
            if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                errors.append(f"{item_path} must have a string id")
                continue
            item_id = item["id"]
            if item_id in all_ids:
                errors.append(f"duplicate id {item_id}: {all_ids[item_id]} and {item_path}")
            all_ids[item_id] = item_path
            indexes[collection_name].add(item_id)
            if not item.get("source_refs"):
                errors.append(f"{item_path} has no source_refs")

    for path, value in walk(package):
        if isinstance(value, dict):
            for field, collection_name in SINGLE_REFERENCE_FIELDS.items():
                reference = value.get(field)
                if reference is not None and reference not in indexes.get(collection_name, set()):
                    errors.append(f"{path}.{field} references missing {reference}")
            for field, collection_name in MULTI_REFERENCE_FIELDS.items():
                references = value.get(field)
                if references is None:
                    continue
                if not isinstance(references, list):
                    errors.append(f"{path}.{field} must be an array")
                    continue
                for reference in references:
                    if reference not in indexes.get(collection_name, set()):
                        errors.append(f"{path}.{field} references missing {reference}")
        elif isinstance(value, str) and ("TODO" in value or "unresolved" in value.lower()):
            errors.append(f"{path} contains an unresolved placeholder")

    if any(path.endswith(".review_items") for path, _ in walk(package)):
        errors.append("ready package must not contain review_items")

    for index, scene in enumerate(content.get("scenes", [])):
        for field in ("player_description", "keeper_notes"):
            if not scene.get(field):
                errors.append(f"content.scenes[{index}].{field} is required")

    for index, checkpoint in enumerate(content.get("checkpoints", [])):
        if not checkpoint.get("skills"):
            errors.append(f"content.checkpoints[{index}].skills is required")
        if not checkpoint.get("difficulty"):
            errors.append(f"content.checkpoints[{index}].difficulty is required")

    ruleset_ref = package.get("module", {}).get("ruleset_ref", {})
    condition_types = set(ruleset_ref.get("required_condition_types", []))
    effect_types = set(ruleset_ref.get("required_effect_types", []))

    def check_conditions(conditions: Any, path: str) -> None:
        if conditions is None:
            return
        if not isinstance(conditions, list):
            errors.append(f"{path} must be an array")
            return
        for index, condition in enumerate(conditions):
            condition_type = condition.get("type") if isinstance(condition, dict) else None
            if condition_type not in condition_types:
                errors.append(f"{path}[{index}] uses unregistered condition type {condition_type}")

    def check_effects(effects: Any, path: str) -> None:
        if effects is None:
            return
        if not isinstance(effects, list):
            errors.append(f"{path} must be an array")
            return
        for index, effect in enumerate(effects):
            effect_type = effect.get("type") if isinstance(effect, dict) else None
            if effect_type not in effect_types:
                errors.append(f"{path}[{index}] uses unregistered effect type {effect_type}")
                continue
            if isinstance(effect, dict) and "then" in effect:
                check_effects(effect["then"], f"{path}[{index}].then")

    for index, clue in enumerate(content.get("clues", [])):
        check_effects(clue.get("effects"), f"content.clues[{index}].effects")
    for index, checkpoint in enumerate(content.get("checkpoints", [])):
        check_conditions(
            checkpoint.get("prerequisites"),
            f"content.checkpoints[{index}].prerequisites",
        )
        for field in ("on_success", "on_failure", "on_fumble"):
            check_effects(checkpoint.get(field), f"content.checkpoints[{index}].{field}")
    for index, trigger in enumerate(content.get("triggers", [])):
        check_conditions(trigger.get("conditions"), f"content.triggers[{index}].conditions")
        check_effects(trigger.get("effects"), f"content.triggers[{index}].effects")
    for index, ending in enumerate(content.get("endings", [])):
        check_conditions(ending.get("conditions"), f"content.endings[{index}].conditions")

    priorities = [ending.get("priority") for ending in content.get("endings", [])]
    if None in priorities:
        errors.append("every ending must have a priority")
    elif len(priorities) != len(set(priorities)):
        errors.append("ending priorities must be unique")

    for cycle in detect_trigger_cycles(content.get("triggers", [])):
        errors.append(f"trigger cycle detected: {cycle}")

    decisions = package.get("normalization_decisions")
    if not isinstance(decisions, list):
        errors.append("normalization_decisions must be an array")
    else:
        for index, decision in enumerate(decisions):
            if decision.get("status") != "resolved":
                errors.append(f"normalization_decisions[{index}] is not resolved")
            for field in ("decision", "policy", "source_refs"):
                if not decision.get(field):
                    errors.append(f"normalization_decisions[{index}].{field} is required")

    module = package.get("module", {})
    initial_state = package.get("initial_state", {})
    entry_scene_id = module.get("entry_scene_id")
    if entry_scene_id not in indexes.get("scenes", set()):
        errors.append("module.entry_scene_id must reference an existing scene")
    if initial_state.get("current_scene_id") != entry_scene_id:
        errors.append("initial_state.current_scene_id must equal module.entry_scene_id")

    ruleset_ref = module.get("ruleset_ref", {})
    for field in (
        "system_id",
        "version",
        "required_capabilities",
        "required_condition_types",
        "required_effect_types",
    ):
        if not ruleset_ref.get(field):
            errors.append(f"module.ruleset_ref.{field} is required")

    keeper_brief = package.get("keeper_brief", {})
    for field in ("core_truth", "experience_goal", "must_preserve"):
        if not keeper_brief.get(field):
            errors.append(f"keeper_brief.{field} is required")

    validation = package.get("validation", {})
    if validation.get("status") != "passed" or validation.get("errors") != []:
        errors.append("validation summary must be passed with no errors")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    args = parser.parse_args()

    try:
        package = json.loads(args.package.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 1

    errors = validate(package)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    counts = {name: len(package["content"][name]) for name in CONTENT_COLLECTIONS}
    print(f"VALID: {package['package_id']}")
    print(json.dumps(counts, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
