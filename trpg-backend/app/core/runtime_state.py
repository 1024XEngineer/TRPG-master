"""Helpers for materializing ruleset data into persisted Actor runtime snapshots."""

from copy import deepcopy

from app.core.coc7_rules import evaluate_skill_base


def ruleset_skill_values(
    entries: object,
    *,
    attributes: dict,
) -> dict[str, int]:
    """Materialize every ruleset skill base for the supplied Actor attributes."""

    if not isinstance(entries, list):
        return {}
    numeric_attributes = {
        key: value
        for key, value in attributes.items()
        if isinstance(key, str) and isinstance(value, int) and not isinstance(value, bool)
    }
    values: dict[str, int] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        skill_id = entry.get("id")
        base = entry.get("base")
        if (
            not isinstance(skill_id, str)
            or not skill_id.strip()
            or isinstance(base, bool)
            or not isinstance(base, (int, str))
        ):
            continue
        values[skill_id] = evaluate_skill_base(base, numeric_attributes)
    return values


def ruleset_labels(
    entries: object,
    *,
    id_field: str,
    name_field: str,
) -> dict[str, str]:
    if not isinstance(entries, list):
        return {}
    labels: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        item_id = entry.get(id_field)
        name = entry.get(name_field)
        if isinstance(item_id, str) and isinstance(name, str) and name.strip():
            labels[item_id] = name
    return labels


def hydrate_actor_state_from_ruleset(
    actor_state: dict,
    ruleset: dict | None,
) -> tuple[dict, bool]:
    """Backfill ruleset bases while preserving every value already owned by the Actor."""

    if not isinstance(ruleset, dict):
        return actor_state, False

    hydrated = deepcopy(actor_state)
    attributes = hydrated.get("attributes")
    if not isinstance(attributes, dict):
        attributes = {}

    base_skills = ruleset_skill_values(
        ruleset.get("skills"),
        attributes=attributes,
    )
    if base_skills:
        current_skills = hydrated.get("skills")
        if isinstance(current_skills, dict):
            base_skills.update(current_skills)
        hydrated["skills"] = base_skills

    attribute_labels = ruleset_labels(
        ruleset.get("attributes"),
        id_field="key",
        name_field="label",
    )
    if attribute_labels:
        current_attribute_labels = hydrated.get("attribute_labels")
        if isinstance(current_attribute_labels, dict):
            attribute_labels.update(current_attribute_labels)
        hydrated["attribute_labels"] = attribute_labels

    skill_labels = ruleset_labels(
        ruleset.get("skills"),
        id_field="id",
        name_field="name",
    )
    if skill_labels:
        current_skill_labels = hydrated.get("skill_labels")
        if isinstance(current_skill_labels, dict):
            skill_labels.update(current_skill_labels)
        hydrated["skill_labels"] = skill_labels

    return hydrated, hydrated != actor_state
