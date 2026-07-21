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
    "locations",
    "entities",
    "characters",
    "resources",
    "clues",
    "checkpoints",
    "sanity_events",
    "timelines",
    "tracks",
    "encounters",
    "puzzles",
    "tables",
    "triggers",
    "endings",
)

SINGLE_REFERENCE_FIELDS = {
    "scene_id": "scenes",
    "current_scene_id": "scenes",
    "location_id": "locations",
    "parent_location_id": "locations",
    "entity_id": "entities",
    "owner_entity_id": "entities",
    "character_id": "characters",
    "resource_id": "resources",
    "clue_id": "clues",
    "discovery_clue_id": "clues",
    "checkpoint_id": "checkpoints",
    "sanity_event_id": "sanity_events",
    "timeline_id": "timelines",
    "track_id": "tracks",
    "encounter_id": "encounters",
    "puzzle_id": "puzzles",
    "table_id": "tables",
    "trigger_id": "triggers",
    "ending_id": "endings",
    "active_ending_id": "endings",
    "active_encounter_id": "encounters",
    "asset_id": "assets",
}

MULTI_REFERENCE_FIELDS = {
    "next_scene_ids": "scenes",
    "scene_ids": "scenes",
    "location_ids": "locations",
    "entity_ids": "entities",
    "linked_entity_ids": "entities",
    "participant_entity_ids": "entities",
    "pregenerated_character_ids": "characters",
    "resource_ids": "resources",
    "clue_ids": "clues",
    "granted_clue_ids": "clues",
    "reveal_after_clue_ids": "clues",
    "checkpoint_ids": "checkpoints",
    "completed_checkpoint_ids": "checkpoints",
    "available_checkpoint_ids": "checkpoints",
    "timeline_ids": "timelines",
    "active_timeline_ids": "timelines",
    "track_ids": "tracks",
    "encounter_ids": "encounters",
    "puzzle_ids": "puzzles",
    "asset_ids": "assets",
    "linked_location_ids": "locations",
    "inventory_resource_ids": "resources",
    "trigger_ids": "triggers",
    "fired_trigger_ids": "triggers",
    "ending_ids": "endings",
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

    if package.get("package_schema_version") != "1.1.0":
        errors.append("package_schema_version must be '1.1.0'")

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
            if not isinstance(item, dict):
                errors.append(f"{item_path} must be an object")
                continue
            item_id = item.get("id")
            if not isinstance(item_id, str):
                errors.append(f"{item_path} must have a string id")
                continue
            if item_id in all_ids:
                errors.append(f"duplicate id {item_id}: {all_ids[item_id]} and {item_path}")
            all_ids[item_id] = item_path
            indexes[collection_name].add(item_id)
            if not item.get("source_refs"):
                errors.append(f"{item_path} has no source_refs")

    assets = package.get("assets")
    indexes["assets"] = set()
    if not isinstance(assets, list):
        errors.append("assets must be an array")
    else:
        for index, asset in enumerate(assets):
            asset_path = f"assets[{index}]"
            if not isinstance(asset, dict):
                errors.append(f"{asset_path} must be an object")
                continue
            asset_id = asset.get("id")
            if not isinstance(asset_id, str):
                errors.append(f"{asset_path} must have a string id")
                continue
            if asset_id in all_ids:
                errors.append(f"duplicate id {asset_id}: {all_ids[asset_id]} and {asset_path}")
            all_ids[asset_id] = asset_path
            indexes["assets"].add(asset_id)

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

    for index, location in enumerate(content.get("locations", [])):
        for field in ("name", "kind"):
            if not location.get(field):
                errors.append(f"content.locations[{index}].{field} is required")
        connections = location.get("connections")
        if not isinstance(connections, list):
            errors.append(f"content.locations[{index}].connections must be an array")
        else:
            for connection_index, connection in enumerate(connections):
                if not isinstance(connection, dict):
                    errors.append(
                        f"content.locations[{index}].connections[{connection_index}] "
                        "must be an object"
                    )
                    continue
                if connection.get("kind") == "hidden_route" and not (
                    connection.get("discovery_clue_id") or connection.get("conditions")
                ):
                    errors.append(
                        f"content.locations[{index}].connections[{connection_index}] "
                        "hidden route requires discovery_clue_id or conditions"
                    )

    for index, character in enumerate(content.get("characters", [])):
        for field in ("name", "stat_block"):
            if not character.get(field):
                errors.append(f"content.characters[{index}].{field} is required")

    for index, resource in enumerate(content.get("resources", [])):
        for field in ("name", "kind"):
            if not resource.get(field):
                errors.append(f"content.resources[{index}].{field} is required")

    for index, encounter in enumerate(content.get("encounters", [])):
        for field in ("name", "kind", "resolution"):
            if not encounter.get(field):
                errors.append(f"content.encounters[{index}].{field} is required")

    for index, timeline in enumerate(content.get("timelines", [])):
        for field in ("name", "clock", "events"):
            if not timeline.get(field):
                errors.append(f"content.timelines[{index}].{field} is required")

    for index, track in enumerate(content.get("tracks", [])):
        for field in ("name", "initial_state", "states", "transitions"):
            if field not in track:
                errors.append(f"content.tracks[{index}].{field} is required")

    for index, puzzle in enumerate(content.get("puzzles", [])):
        for field in ("name", "goal", "nodes"):
            if not puzzle.get(field):
                errors.append(f"content.puzzles[{index}].{field} is required")

    for index, table in enumerate(content.get("tables", [])):
        for field in ("name", "selection_mode", "entries"):
            if not table.get(field):
                errors.append(f"content.tables[{index}].{field} is required")

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
            if not isinstance(effect, dict):
                errors.append(f"{path}[{index}] must be an object")
                continue
            effect_type = effect.get("type")
            if effect_type not in effect_types:
                errors.append(f"{path}[{index}] uses unregistered effect type {effect_type}")
                continue
            nested_effects = effect.get("then")
            if nested_effects is not None:
                check_effects(nested_effects, f"{path}[{index}].then")

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

    for index, timeline in enumerate(content.get("timelines", [])):
        for event_index, event in enumerate(timeline.get("events", [])):
            event_path = f"content.timelines[{index}].events[{event_index}]"
            check_conditions(event.get("conditions"), f"{event_path}.conditions")
            check_effects(event.get("effects"), f"{event_path}.effects")

    for index, track in enumerate(content.get("tracks", [])):
        for transition_index, transition in enumerate(track.get("transitions", [])):
            transition_path = f"content.tracks[{index}].transitions[{transition_index}]"
            check_conditions(transition.get("conditions"), f"{transition_path}.conditions")
            check_effects(transition.get("effects"), f"{transition_path}.effects")

    for index, encounter in enumerate(content.get("encounters", [])):
        encounter_path = f"content.encounters[{index}]"
        check_conditions(encounter.get("start_conditions"), f"{encounter_path}.start_conditions")
        check_effects(encounter.get("on_start"), f"{encounter_path}.on_start")
        check_effects(encounter.get("on_end"), f"{encounter_path}.on_end")

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
            if not isinstance(decision, dict):
                errors.append(f"normalization_decisions[{index}] must be an object")
                continue
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
    for field, expected_type in (
        ("active_timeline_ids", list),
        ("track_states", dict),
        ("inventory_resource_ids", list),
    ):
        if not isinstance(initial_state.get(field), expected_type):
            errors.append(f"initial_state.{field} must be a {expected_type.__name__}")
    if "active_encounter_id" not in initial_state:
        errors.append("initial_state.active_encounter_id is required")

    character_setup = module.get("character_setup")
    if not isinstance(character_setup, dict):
        errors.append("module.character_setup must be an object")
    else:
        for field in (
            "creation_mode",
            "requirements",
            "recommended_skills",
            "party_relationships",
            "pregenerated_character_ids",
            "personalization_slots",
        ):
            if field not in character_setup:
                errors.append(f"module.character_setup.{field} is required")

    entry_points = module.get("entry_points")
    if not isinstance(entry_points, list) or not entry_points:
        errors.append("module.entry_points must be a non-empty array")
    if not isinstance(module.get("content_advisories"), list):
        errors.append("module.content_advisories must be an array")

    source_manifest = package.get("source_manifest", {})
    segments = source_manifest.get("segments")
    if not isinstance(segments, list) or not segments:
        errors.append("source_manifest.segments must be a non-empty array")
    rights = source_manifest.get("rights")
    if not isinstance(rights, dict):
        errors.append("source_manifest.rights must be an object")
    else:
        for field in ("declaration_status", "commercial_use", "redistribution"):
            if not rights.get(field):
                errors.append(f"source_manifest.rights.{field} is required")
    extraction_quality = source_manifest.get("extraction_quality")
    if not isinstance(extraction_quality, dict):
        errors.append("source_manifest.extraction_quality must be an object")
    else:
        for field in ("text_confidence", "layout_confidence", "asset_coverage"):
            value = extraction_quality.get(field)
            if not isinstance(value, (int, float)) or not 0 <= value <= 1:
                errors.append(f"source_manifest.extraction_quality.{field} must be between 0 and 1")

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
    if validation.get("validator_version") != "module-package-validator/0.2.0":
        errors.append("validation.validator_version must be module-package-validator/0.2.0")

    for index, asset in enumerate(assets if isinstance(assets, list) else []):
        if asset.get("kind") == "map" and not asset.get("linked_location_ids"):
            errors.append(f"assets[{index}] map must have linked_location_ids")
        if asset.get("runtime_use") == "npc_reveal" and not asset.get("linked_entity_ids"):
            errors.append(f"assets[{index}] npc_reveal must have linked_entity_ids")

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
