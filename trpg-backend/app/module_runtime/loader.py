"""ModulePackage 的文件加载、发布校验与运行时索引编译。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.module_runtime.models import ModulePackage

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


class ModulePackageError(ValueError):
    """模组包不能被安全发布或运行。"""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("ModulePackage 校验失败：" + "；".join(errors))


@dataclass(frozen=True)
class RuntimeModule:
    package: ModulePackage
    package_json: dict[str, Any]
    checksum: str
    indexes: dict[str, dict[str, dict[str, Any]]]

    def get(self, collection: str, item_id: str) -> dict[str, Any] | None:
        return self.indexes.get(collection, {}).get(item_id)

    @property
    def entry_scene(self) -> dict[str, Any]:
        scene = self.get("scenes", self.package.module.entry_scene_id)
        if scene is None:  # pragma: no cover - semantic validation prevents this.
            raise ModulePackageError(["entry_scene_id references a missing scene"])
        return scene

    @property
    def development_only(self) -> bool:
        return not self.package.source_manifest.rights.cleared_for_distribution


def _walk(value: Any, path: str = "$"):
    yield path, value
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _walk(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk(child, f"{path}[{index}]")


def _trigger_cycles(triggers: list[dict[str, Any]]) -> list[str]:
    graph = {str(trigger["id"]): set() for trigger in triggers}
    for trigger in triggers:
        for _, value in _walk(trigger.get("effects", [])):
            if isinstance(value, dict) and value.get("type") == "fire_trigger":
                target = value.get("trigger_id")
                if isinstance(target, str):
                    graph[str(trigger["id"])].add(target)

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


class ModuleLoader:
    """加载并编译一个不可变的 ModulePackage revision。"""

    @staticmethod
    def default_package_path() -> Path:
        repository_root = Path(__file__).resolve().parents[3]
        return repository_root / "docs/module-parser/paper-chase/module-package.json"

    def load_default(self, *, allow_uncleared: bool) -> RuntimeModule:
        return self.load_path(self.default_package_path(), allow_uncleared=allow_uncleared)

    def load_path(self, path: Path, *, allow_uncleared: bool) -> RuntimeModule:
        try:
            raw_bytes = path.read_bytes()
        except OSError as exc:
            raise ModulePackageError([f"cannot read package: {path}"]) from exc
        try:
            package_json = json.loads(raw_bytes)
        except json.JSONDecodeError as exc:
            raise ModulePackageError([f"invalid JSON: {exc}"]) from exc
        return self.load_dict(
            package_json,
            checksum=hashlib.sha256(raw_bytes).hexdigest(),
            allow_uncleared=allow_uncleared,
        )

    def load_dict(
        self,
        package_json: dict[str, Any],
        *,
        checksum: str | None = None,
        allow_uncleared: bool,
    ) -> RuntimeModule:
        try:
            package = ModulePackage.model_validate(package_json)
        except ValidationError as exc:
            errors = [
                f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
                for error in exc.errors()
            ]
            raise ModulePackageError(errors) from exc

        errors, indexes = self._validate_semantics(package_json, package)
        if package.validation.status != "passed" or package.validation.errors:
            errors.append("embedded validation block is not passed")
        if not allow_uncleared and not package.source_manifest.rights.cleared_for_distribution:
            errors.append("module rights are not cleared for runtime distribution")
        if errors:
            raise ModulePackageError(errors)

        canonical = json.dumps(package_json, ensure_ascii=False, sort_keys=True).encode()
        return RuntimeModule(
            package=package,
            package_json=package_json,
            checksum=checksum or hashlib.sha256(canonical).hexdigest(),
            indexes=indexes,
        )

    def _validate_semantics(
        self, package_json: dict[str, Any], package: ModulePackage
    ) -> tuple[list[str], dict[str, dict[str, dict[str, Any]]]]:
        errors: list[str] = []
        indexes: dict[str, dict[str, dict[str, Any]]] = {}
        global_ids: dict[str, str] = {}
        content = package_json["content"]

        for collection_name in CONTENT_COLLECTIONS:
            indexes[collection_name] = {}
            for index, item in enumerate(content[collection_name]):
                path = f"content.{collection_name}[{index}]"
                item_id = item.get("id")
                if not isinstance(item_id, str) or not item_id:
                    errors.append(f"{path} has no string id")
                    continue
                if item_id in global_ids:
                    errors.append(f"duplicate id {item_id}: {global_ids[item_id]} and {path}")
                global_ids[item_id] = path
                indexes[collection_name][item_id] = item
                if not item.get("source_refs"):
                    errors.append(f"{path} has no source_refs")

        indexes["assets"] = {}
        for index, asset in enumerate(package_json["assets"]):
            asset_id = asset.get("id")
            path = f"assets[{index}]"
            if not isinstance(asset_id, str) or not asset_id:
                errors.append(f"{path} has no string id")
                continue
            if asset_id in global_ids:
                errors.append(f"duplicate id {asset_id}: {global_ids[asset_id]} and {path}")
            global_ids[asset_id] = path
            indexes["assets"][asset_id] = asset

        id_sets = {name: set(items) for name, items in indexes.items()}
        for path, value in _walk(package_json):
            if not isinstance(value, dict):
                continue
            for field, collection_name in SINGLE_REFERENCE_FIELDS.items():
                reference = value.get(field)
                if reference is not None and reference not in id_sets.get(collection_name, set()):
                    errors.append(f"{path}.{field} references missing {reference}")
            for field, collection_name in MULTI_REFERENCE_FIELDS.items():
                references = value.get(field)
                if references is None:
                    continue
                if not isinstance(references, list):
                    errors.append(f"{path}.{field} must be an array")
                    continue
                for reference in references:
                    if reference not in id_sets.get(collection_name, set()):
                        errors.append(f"{path}.{field} references missing {reference}")

        condition_types = set(package.module.ruleset_ref.required_condition_types)
        effect_types = set(package.module.ruleset_ref.required_effect_types)
        for path, value in _walk(package_json):
            if not isinstance(value, dict) or "type" not in value:
                continue
            item_type = value["type"]
            if ".conditions" in path or ".prerequisites" in path:
                if item_type not in condition_types:
                    errors.append(f"{path} uses unregistered condition type {item_type}")
            elif (
                ".effects" in path
                or ".on_success" in path
                or ".on_failure" in path
                or ".on_fumble" in path
                or ".then" in path
            ) and item_type not in effect_types:
                errors.append(f"{path} uses unregistered effect type {item_type}")

        for cycle in _trigger_cycles(content["triggers"]):
            errors.append(f"trigger cycle: {cycle}")
        if package.module.entry_scene_id not in indexes["scenes"]:
            errors.append("module.entry_scene_id is missing")
        if package.initial_state.current_scene_id not in indexes["scenes"]:
            errors.append("initial_state.current_scene_id is missing")

        pregen_ids = package.module.character_setup.pregenerated_character_ids
        if package.module.character_setup.creation_mode == "pregen" and not pregen_ids:
            errors.append("pregen character setup requires at least one character")

        return errors, indexes
