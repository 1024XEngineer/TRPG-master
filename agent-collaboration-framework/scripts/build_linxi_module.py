"""生成《林隙的罪恶》的 ModuleContentV3、来源映射和审查报告。

原文全文作为背景和来源保存；规则只使用当前引擎已注册的效果、检定和终局事实。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MODULE_DIR = ROOT / "docs/module-parser/examples/module-content-validation/林隙的罪恶"
SOURCE = MODULE_DIR / "林隙的罪恶-Butterrr.txt"
OUTPUT = MODULE_DIR / "module-content-v3.json"
PROVENANCE = MODULE_DIR / "module-content-provenance.json"
REVIEW = MODULE_DIR / "module-content-review.md"


def info(
    item_id: str, title: str, keeper: str, player: str, criticality: str = "supporting"
) -> dict[str, Any]:
    """构造 Keeper 与玩家文本分离的权威线索。"""

    return {
        "id": item_id,
        "kind": "fact",
        "title": title,
        "keeper_content": keeper,
        "player_content": player,
        "criticality": criticality,
        "recovery": {
            "policy": "adaptive",
            "allowed_source_types": ["explicit_entity", "explicit_location"],
        },
    }


def entity(
    item_id: str,
    name: str,
    description: str,
    location: str,
    *,
    state: dict[str, Any] | None = None,
    npc: bool = False,
    portable: bool = False,
) -> dict[str, Any]:
    """构造不可运行时凭空生成的 Canon 实体。"""

    result: dict[str, Any] = {
        "id": item_id,
        "kind": "npc" if npc else "object",
        "name": name,
        "player_visible_name": name,
        "description": description,
        "located_in": location,
        "state": state or {},
        "visibility": "public",
        "plot_relevance": True,
    }
    if portable:
        result["item_component"] = {"portable": True, "unique": True, "quantity": 1}
    return result


def effect_rule(
    rule_id: str,
    families: list[str],
    location: str,
    target_kind: str,
    target_id: str,
    option: str,
    hints: list[str],
    effects: list[dict[str, Any]],
) -> dict[str, Any]:
    """构造确定性行动规则，所有状态变化都经过正式 effect。"""

    steps = []
    for index, effect in enumerate(effects):
        steps.append(
            {
                "id": f"success_{index}",
                "kind": "effect",
                "effect": effect,
                "next_step_id": f"success_{index + 1}"
                if index + 1 < len(effects)
                else "finish",
            }
        )
    steps.append({"id": "finish", "kind": "finish"})
    return {
        "id": rule_id,
        "trigger": {
            "kind": "agent_match",
            "scope": {
                "action_families": families,
                "location_ids": [location],
                "target_kinds": [target_kind],
                "target_ids": [target_id],
            },
            "question": {"kind": "method", "semantic_hints": hints},
            "options": [{"id": option, "semantic_hints": hints}],
        },
        "execution": {
            "branches": [{"id": option, "entry_step_id": "success_0"}],
            "steps": steps,
        },
    }


def check_rule(
    rule_id: str,
    families: list[str],
    location: str,
    target_id: str,
    option: str,
    skill_id: str,
    success: list[dict[str, Any]],
    failure: list[dict[str, Any]],
) -> dict[str, Any]:
    """构造失败可重试的 COC7 技能检定规则。"""

    steps: list[dict[str, Any]] = [
        {
            "id": "check",
            "kind": "check",
            "check": {
                "profile_id": "coc7.skill",
                "actor_binding": "actor",
                "initiation_kind": "active_action",
                "parameters": {"skill_id": skill_id},
                "difficulty": "regular",
            },
            "result_routes": {
                "critical_success": "success_0",
                "extreme_success": "success_0",
                "hard_success": "success_0",
                "regular_success": "success_0",
                "failure": "failure_0",
                "fumble": "failure_0",
            },
        }
    ]
    for prefix, effects in (("success", success), ("failure", failure)):
        for index, effect in enumerate(effects):
            steps.append(
                {
                    "id": f"{prefix}_{index}",
                    "kind": "effect",
                    "effect": effect,
                    "next_step_id": f"{prefix}_{index + 1}"
                    if index + 1 < len(effects)
                    else "finish",
                }
            )
    steps.append({"id": "finish", "kind": "finish"})
    return {
        "id": rule_id,
        "trigger": {
            "kind": "agent_match",
            "scope": {
                "action_families": families,
                "location_ids": [location],
                "target_kinds": ["entity"],
                "target_ids": [target_id],
            },
            "question": {"kind": "method", "semantic_hints": [skill_id, option]},
            "options": [{"id": option, "semantic_hints": [skill_id, option]}],
        },
        "execution": {
            "branches": [{"id": option, "entry_step_id": "check"}],
            "steps": steps,
        },
    }


def move_rule(
    rule_id: str, location: str, target: str, option: str, effects: list[dict[str, Any]]
) -> dict[str, Any]:
    """构造地点进入规则，并把逃生事实交给规则引擎提交。"""

    return effect_rule(
        rule_id,
        ["enter", "leave", "escape"],
        location,
        "location",
        target,
        option,
        ["进入", target],
        effects,
    )


def build() -> dict[str, Any]:
    """从原文生成稳定的多人调查主线。"""

    source = SOURCE.read_text(encoding="utf-8")
    information = [
        info(
            "cabin_layout",
            "木屋布局",
            "木屋分为柴房、客厅、厨房、卧室和地下室，入口由铃铛围栏监视。",
            "你了解了木屋的主要房间、柴房和围栏布局。",
            "essential",
        ),
        info(
            "animal_traps",
            "树林里的捕兽陷阱",
            "屋外陷阱解释了动物稀少，也能成为逃跑时的危险。",
            "林间有捕兽夹和绊线，附近的动物异常稀少。",
        ),
        info(
            "esau_sick",
            "以扫的异常病症",
            "以扫的梦游、酗酒和烟草问题与夏盖寄生有关。",
            "以扫长期失眠、梦游，并且身体状况明显恶化。",
            "essential",
        ),
        info(
            "diary_truth",
            "日记中的异常记录",
            "日记记录动物尸体、红色地下室和不可辨识的名字。",
            "日记把动物尸体、地下室和某个无法辨认的名字联系在一起。",
            "essential",
        ),
        info(
            "basement_horror",
            "地下室的血肉亵渎",
            "地下室是夏盖活动和残杀动物的现场，可获得酒精作为环境手段。",
            "地下室被血肉和器官覆盖，墙上留下了令人作呕的图案。",
            "essential",
        ),
        info(
            "night_attack",
            "梦游猎杀",
            "入夜后夏盖操控以扫追杀留宿的调查员。",
            "夜里以扫拿着猎枪和猎刀醒来，动作像没有灵魂的木偶。",
            "essential",
        ),
        info(
            "esau_defeated",
            "以扫失去行动能力",
            "调查员通过陷阱、逃跑配合或一次受裁决的反击使以扫失去追杀能力。",
            "以扫倒下，暂时无法继续追杀你们。",
            "essential",
        ),
        info(
            "escape_route",
            "木屋外的逃生路线",
            "正门、围栏和烟囱都可以成为离开木屋的路线。",
            "你找到了离开木屋和绕过铃铛围栏的办法。",
            "essential",
        ),
        info(
            "shoggoth_revealed",
            "雅各现身",
            "以扫倒下后，寄生在他脑内的夏盖妖虫从头颅中穿出。",
            "一只昆虫般的造物从以扫身上飞出，真相终于显形。",
        ),
        info(
            "investigator_escaped",
            "调查员逃离荒野木屋",
            "调查员离开木屋并完成本次核心目标。",
            "你们离开了木屋，暂时摆脱了追杀。",
            "essential",
        ),
    ]
    entities = [
        entity("cabin", "以扫的木屋", "由原木和石头搭建的二层木屋。", "cabin_exterior"),
        entity(
            "bell_fence",
            "铃铛围栏",
            "围住柴房和木屋，触碰会发出声响。",
            "cabin_exterior",
            state={"crossed": False},
        ),
        entity(
            "animal_trap",
            "捕兽夹与绊线",
            "树林中稀疏分布的陷阱。",
            "forest",
            state={"noticed": False},
        ),
        entity(
            "wood_shed",
            "柴房",
            "堆放柴火、工具和捕兽夹的上锁杂物室。",
            "cabin_exterior",
            state={"opened": False},
        ),
        entity(
            "living_room",
            "客厅地毯",
            "壁炉和动物标本旁的地毯掩盖着地下室入口。",
            "cabin",
            state={"moved": False},
        ),
        entity(
            "bedside_drawer",
            "以扫卧室床头柜",
            "藏着日记、病历和地下室钥匙。",
            "esau_bedroom",
            state={"searched": False},
        ),
        entity(
            "esau_diary",
            "以扫的日记",
            "记录猎物、梦游和地下室异常的日记。",
            "esau_bedroom",
            state={"read": False},
        ),
        entity(
            "basement",
            "血肉地下室",
            "酿酒器材和被残杀动物的地下空间。",
            "basement",
            state={"seen": False},
        ),
        entity(
            "esau",
            "以扫·斯潘",
            "32岁的猎人，受到夏盖妖虫寄生。",
            "cabin",
            state={"awake": True, "defeated": False},
            npc=True,
        ),
        entity(
            "shub_niggurath",
            "夏盖妖虫·雅各",
            "寄生在以扫脑内的神话生物。",
            "cabin",
            state={"revealed": False},
            npc=True,
        ),
        entity(
            "hunting_rifle",
            "猎枪",
            "以扫夜间追杀时使用的武器。",
            "esau_bedroom",
            portable=True,
        ),
        entity(
            "skinning_knife",
            "割皮猎刀",
            "以扫随身携带的猎刀。",
            "esau_bedroom",
            portable=True,
        ),
        entity(
            "workbench",
            "柴房工作台",
            "可以将柴房材料组合成阻拦或逃生工具。",
            "cabin_exterior",
        ),
    ]
    rules = [
        move_rule(
            "enter_cabin",
            "cabin_exterior",
            "cabin",
            "enter-cabin",
            [{"type": "enter_location", "location_id": "cabin"}],
        ),
        move_rule(
            "enter_esau_bedroom",
            "cabin",
            "esau_bedroom",
            "enter-bedroom",
            [{"type": "enter_location", "location_id": "esau_bedroom"}],
        ),
        move_rule(
            "enter_basement",
            "cabin",
            "basement",
            "enter-basement",
            [{"type": "enter_location", "location_id": "basement"}],
        ),
        move_rule(
            "enter_forest",
            "cabin",
            "forest",
            "enter-forest",
            [{"type": "enter_location", "location_id": "forest"}],
        ),
        move_rule(
            "leave_forest",
            "forest",
            "cabin_exterior",
            "leave-forest",
            [{"type": "enter_location", "location_id": "cabin_exterior"}],
        ),
        effect_rule(
            "inspect_cabin",
            ["inspect", "search", "observe"],
            "cabin_exterior",
            "entity",
            "cabin",
            "survey-cabin",
            ["木屋", "布局"],
            [
                {
                    "type": "change_entity_state",
                    "entity_id": "cabin",
                    "key": "surveyed",
                    "value": True,
                },
                {
                    "type": "reveal_information",
                    "information_id": "cabin_layout",
                    "scope": "party",
                },
            ],
        ),
        check_rule(
            "find_traps",
            ["search", "observe", "listen"],
            "forest",
            "animal_trap",
            "notice-traps",
            "spot-hidden",
            [
                {
                    "type": "change_entity_state",
                    "entity_id": "animal_trap",
                    "key": "noticed",
                    "value": True,
                },
                {
                    "type": "reveal_information",
                    "information_id": "animal_traps",
                    "scope": "party",
                },
            ],
            [
                {
                    "type": "reveal_information",
                    "information_id": "animal_traps",
                    "scope": "party",
                }
            ],
        ),
        check_rule(
            "assess_esau",
            ["talk", "medical", "observe"],
            "cabin",
            "esau",
            "assess-esau",
            "medicine",
            [
                {
                    "type": "reveal_information",
                    "information_id": "esau_sick",
                    "scope": "party",
                }
            ],
            [
                {
                    "type": "reveal_information",
                    "information_id": "esau_sick",
                    "scope": "party",
                }
            ],
        ),
        effect_rule(
            "open_wood_shed",
            ["unlock", "force", "open"],
            "cabin_exterior",
            "entity",
            "wood_shed",
            "open-shed",
            ["柴房", "开锁"],
            [
                {
                    "type": "change_entity_state",
                    "entity_id": "wood_shed",
                    "key": "opened",
                    "value": True,
                }
            ],
        ),
        check_rule(
            "read_esau_diary",
            ["search", "read", "inspect"],
            "esau_bedroom",
            "bedside_drawer",
            "read-diary",
            "spot-hidden",
            [
                {
                    "type": "change_entity_state",
                    "entity_id": "bedside_drawer",
                    "key": "searched",
                    "value": True,
                },
                {
                    "type": "change_entity_state",
                    "entity_id": "esau_diary",
                    "key": "read",
                    "value": True,
                },
                {
                    "type": "reveal_information",
                    "information_id": "diary_truth",
                    "scope": "party",
                },
            ],
            [
                {
                    "type": "reveal_information",
                    "information_id": "diary_truth",
                    "scope": "party",
                }
            ],
        ),
        check_rule(
            "inspect_basement",
            ["search", "inspect", "enter"],
            "cabin",
            "living_room",
            "find-basement",
            "spot-hidden",
            [
                {
                    "type": "change_entity_state",
                    "entity_id": "living_room",
                    "key": "moved",
                    "value": True,
                },
                {
                    "type": "change_entity_state",
                    "entity_id": "basement",
                    "key": "seen",
                    "value": True,
                },
                {
                    "type": "reveal_information",
                    "information_id": "basement_horror",
                    "scope": "party",
                },
            ],
            [
                {
                    "type": "reveal_information",
                    "information_id": "basement_horror",
                    "scope": "party",
                }
            ],
        ),
        check_rule(
            "night_listen",
            ["listen", "observe"],
            "cabin",
            "esau",
            "hear-hunting",
            "listen",
            [
                {
                    "type": "change_entity_state",
                    "entity_id": "esau",
                    "key": "awake",
                    "value": False,
                },
                {
                    "type": "reveal_information",
                    "information_id": "night_attack",
                    "scope": "party",
                },
            ],
            [
                {
                    "type": "reveal_information",
                    "information_id": "night_attack",
                    "scope": "party",
                }
            ],
        ),
        check_rule(
            "escape_house",
            ["sneak", "escape", "climb"],
            "cabin",
            "bell_fence",
            "escape-house",
            "stealth",
            [
                {
                    "type": "change_entity_state",
                    "entity_id": "bell_fence",
                    "key": "crossed",
                    "value": True,
                },
                {
                    "type": "reveal_information",
                    "information_id": "escape_route",
                    "scope": "party",
                },
                {
                    "type": "reveal_information",
                    "information_id": "investigator_escaped",
                    "scope": "party",
                },
                {"type": "mark_core_resolved"},
                {"type": "set_ending_availability", "available": True},
            ],
            [
                {
                    "type": "reveal_information",
                    "information_id": "escape_route",
                    "scope": "party",
                }
            ],
        ),
        {
            "id": "confront_esau",
            "trigger": {
                "kind": "agent_match",
                "scope": {
                    "action_families": ["fight", "attack", "disarm"],
                    "location_ids": ["cabin", "forest"],
                    "target_kinds": ["entity"],
                    "target_ids": ["esau"],
                },
                "question": {
                    "kind": "method",
                    "semantic_hints": ["反击", "陷阱", "使以扫失去行动能力"],
                },
                "options": [{"id": "confront", "semantic_hints": ["反击以扫"]}],
            },
            "execution": {
                "branches": [{"id": "confront", "entry_step_id": "check"}],
                "steps": [
                    {
                        "id": "check",
                        "kind": "adjudicated_check",
                        "adjudication_ref": "current",
                        "effect_authority": "rule",
                        "result_routes": {
                            "critical_success": "success_0",
                            "extreme_success": "success_0",
                            "hard_success": "success_0",
                            "regular_success": "success_0",
                            "failure": "failure_0",
                            "fumble": "failure_0",
                        },
                        "cancel_step_id": "finish",
                    },
                    {
                        "id": "success_0",
                        "kind": "effect",
                        "effect": {
                            "type": "change_entity_state",
                            "entity_id": "esau",
                            "key": "defeated",
                            "value": True,
                        },
                        "next_step_id": "success_1",
                    },
                    {
                        "id": "success_1",
                        "kind": "effect",
                        "effect": {
                            "type": "change_entity_state",
                            "entity_id": "shub_niggurath",
                            "key": "revealed",
                            "value": True,
                        },
                        "next_step_id": "success_2",
                    },
                    {
                        "id": "success_2",
                        "kind": "effect",
                        "effect": {
                            "type": "reveal_information",
                            "information_id": "esau_defeated",
                            "scope": "party",
                        },
                        "next_step_id": "success_3",
                    },
                    {
                        "id": "success_3",
                        "kind": "effect",
                        "effect": {
                            "type": "reveal_information",
                            "information_id": "shoggoth_revealed",
                            "scope": "party",
                        },
                        "next_step_id": "finish",
                    },
                    {"id": "failure_0", "kind": "finish"},
                    {"id": "finish", "kind": "finish"},
                ],
            },
        },
    ]
    return {
        "content_schema_version": 3,
        "module_id": "linxi-sins-zh-coc7",
        "version": "3.0.0",
        "world_ref": "coc-7e",
        "background": source,
        "information": information,
        "knowledge_goals": [
            {
                "id": "understand_cabin",
                "target_information_ids": ["cabin_layout", "esau_sick"],
                "completion": "all",
                "required_for_core_resolution": False,
            },
            {
                "id": "discover_truth",
                "target_information_ids": [
                    "diary_truth",
                    "basement_horror",
                    "night_attack",
                ],
                "completion": "all",
                "required_for_core_resolution": True,
            },
            {
                "id": "escape_alive",
                "target_information_ids": ["investigator_escaped"],
                "completion": "all",
                "required_for_core_resolution": True,
            },
        ],
        "entities": entities,
        "locations": [
            {
                "id": "cabin_exterior",
                "kind": "site",
                "name": "木屋外与铃铛围栏",
                "player_visible_name": "木屋外",
                "player_visible_description": "沃斯堡荒野中的木屋外，柴房和铃铛围栏环绕着入口。",
                "plot_relevance": True,
            },
            {
                "id": "cabin",
                "kind": "room",
                "name": "木屋一楼",
                "player_visible_name": "木屋一楼",
                "player_visible_description": "有壁炉、客厅、厨房和通往二楼的楼梯。",
                "plot_relevance": True,
            },
            {
                "id": "esau_bedroom",
                "kind": "room",
                "name": "以扫的卧室",
                "player_visible_name": "以扫的卧室",
                "player_visible_description": "上锁的卧室，床头柜里藏着日记和病历。",
                "plot_relevance": True,
            },
            {
                "id": "basement",
                "kind": "room",
                "name": "地下室",
                "player_visible_name": "血肉地下室",
                "player_visible_description": "酿酒器材和残杀动物尸体混杂的地下空间。",
                "plot_relevance": True,
            },
            {
                "id": "forest",
                "kind": "site",
                "name": "沃斯堡荒野森林",
                "player_visible_name": "荒野森林",
                "player_visible_description": "木屋四周茂密的森林，陷阱和夜间追逐使这里危险重重。",
                "plot_relevance": True,
            },
        ],
        "location_edges": [
            {
                "id": "outside_to_cabin",
                "from_location_id": "cabin_exterior",
                "to_location_id": "cabin",
                "kind": "public_network",
                "traversal": "automatic",
                "visibility": "public",
            },
            {
                "id": "cabin_to_bedroom",
                "from_location_id": "cabin",
                "to_location_id": "esau_bedroom",
                "kind": "private",
                "traversal": "gated",
                "visibility": "public",
                "access_point_id": "bedside_drawer",
                "conditions": [],
            },
            {
                "id": "cabin_to_basement",
                "from_location_id": "cabin",
                "to_location_id": "basement",
                "kind": "private",
                "traversal": "gated",
                "visibility": "public",
                "access_point_id": "living_room",
                "conditions": [],
            },
            {
                "id": "cabin_to_forest",
                "from_location_id": "cabin",
                "to_location_id": "forest",
                "kind": "public_network",
                "traversal": "automatic",
                "visibility": "public",
            },
            {
                "id": "forest_to_outside",
                "from_location_id": "forest",
                "to_location_id": "cabin_exterior",
                "kind": "public_network",
                "traversal": "automatic",
                "visibility": "public",
            },
        ],
        "rules": rules,
        "core_resolution": {
            "required_goal_ids": ["discover_truth", "escape_alive"],
            "completion": "all",
        },
        "ending_policy": {
            "allow_continue_after_core_resolution": True,
            "require_no_pending_action": True,
            "allow_grounded_variations": True,
            "facets": ["investigator_fate", "esau_fate", "shoggoth_fate"],
        },
        "ending_anchors": [
            {
                "id": "escape_after_confrontation",
                "tone": "grim",
                "required_fact_refs": [
                    "esau_defeated",
                    "shoggoth_revealed",
                    "investigator_escaped",
                ],
                "forbidden_claims": [
                    "uncommitted_investigator_death",
                    "uncommitted_hp_or_san_change",
                ],
            },
            {
                "id": "escape_without_fight",
                "tone": "somber",
                "required_fact_refs": ["investigator_escaped"],
                "forbidden_claims": [
                    "uncommitted_esau_death",
                    "uncommitted_investigator_death",
                ],
            },
        ],
        "presentation": {
            "title": "林隙的罪恶",
            "name_en": "The Sins in the Forest",
            "synopsis": "1920年代德州荒野的木屋里，以扫的梦游病背后藏着不可名状的真相。调查员必须调查异常，并在夜间危险中逃出生天。",
            "players_min": 1,
            "players_max": 3,
            "difficulty": 2,
            "estimated_duration": "2-4 小时",
            "story_label": "LINXI SINS",
            "subtitle": "沃斯堡荒野木屋中的多人调查",
            "authors": ["Butterrr"],
            "tags": ["1920年代", "美国德州", "多人", "克苏鲁恐怖"],
            "player_intro_pages": [
                {
                    "title": "内容提示",
                    "content": "本模组包含绑架、精神疾病描写、动物死亡、血肉恐怖、宗教与神话元素、夜间追杀和可选致命反击。开始前请确认这些内容适合所有参与者。",
                },
                {
                    "title": "调查员准备",
                    "content": "本模组支持1-3名调查员。调查员应认识以扫，建议不携带高伤害武器；侦查、聆听、医学、潜行和敏捷有助于调查与逃生。",
                },
                {
                    "title": "开场",
                    "content": "1920年代傍晚，你们收到朋友以扫的信，前往美国德克萨斯州沃斯堡荒野中的木屋。你们将在夜幕降临前了解这位猎人的病情与住所。",
                },
            ],
        },
        "initial_state": {
            "start_location_id": "cabin_exterior",
            "default_actor_placement": {"location_id": "cabin_exterior"},
            "start_time_point_id": "hour_18",
        },
        "world_profile": {
            "era": "1920年代",
            "region": "美国德克萨斯州沃斯堡荒野",
            "technology_level": "1920年代日常技术",
            "tone": "荒野、寄生、追杀和克苏鲁恐怖",
            "forbidden_content": [
                "Keeper秘密进入玩家视图",
                "Narrator直接宣布死亡或HP/SAN变化",
                "虚构未提交的法术和战斗数值",
            ],
        },
        "time_policy": {
            "default_points": [
                {"id": "hour_06", "hour_of_day": 6, "order": 0},
                {"id": "hour_12", "hour_of_day": 12, "order": 1},
                {"id": "hour_18", "hour_of_day": 18, "order": 2},
                {"id": "hour_22", "hour_of_day": 22, "order": 3},
            ]
        },
    }


def main() -> None:
    """写入固定内容、来源映射和审查报告。"""

    payload = build()
    OUTPUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    collections = {
        key: [item["id"] for item in payload[key]]
        for key in (
            "locations",
            "information",
            "rules",
            "knowledge_goals",
            "ending_anchors",
        )
    }
    PROVENANCE.write_text(
        json.dumps(
            {
                key: {
                    item_id: {
                        "doc_paragraphs": [1],
                        "source": "林隙的罪恶-Butterrr.doc",
                    }
                    for item_id in ids
                }
                for key, ids in collections.items()
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    REVIEW.write_text(
        """# 《林隙的罪恶》ModuleContentV3 审查报告\n\n- 权威来源：`林隙的罪恶-Butterrr.doc`，全文保存在 `background`，玩家开场页仅保留安全摘要。\n- 作者署名：Butterrr；原文声明允许转载及修改后发布，禁止商业用途。\n- 解析范围：木屋外、木屋一楼、以扫卧室、地下室、荒野森林；调查、梦游猎杀、反击、逃跑、躲避和夏盖妖虫真相均有对应事实。\n- 多人简化：全队共享地点与实体状态，行动串行；不模拟逐轮战斗，冲突使用一次 `adjudicated_check`。\n- 质量限制：来源文档是旧式 `.doc`，当前未提供页码元数据，因此 provenance 使用段落来源并明确记录待人工校对。\n- Keeper 隔离：`keeper_content` 只进入 Keeper 侧，玩家字段仅在规则揭示后显示。\n""",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
