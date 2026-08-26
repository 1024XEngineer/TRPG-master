"""生成《银之锁》ModuleContentV3、来源映射和人工审查报告。

该脚本把原文允许的自由裁量收敛为现有规则引擎可确定执行的状态机。所有产物
都是可重复生成的审查文件；不得在这里引入任意物品生成或模组专用自由格式动作。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = (
    ROOT
    / "docs"
    / "module-parser"
    / "examples"
    / "module-content-validation"
    / "银之锁"
)

SUCCESS_ROUTES = {
    "critical_success": "success_0",
    "extreme_success": "success_0",
    "hard_success": "success_0",
    "regular_success": "success_0",
    "failure": "failure_0",
    "fumble": "failure_0",
}


def information(
    item_id: str,
    title: str,
    keeper: str,
    player: str,
    *,
    criticality: str = "supporting",
) -> dict[str, Any]:
    """构造守秘人与玩家正文严格分离的线索。"""

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


def state_is(entity_id: str, key: str, value: Any) -> dict[str, Any]:
    """生成引擎已注册的实体状态谓词，避免自由格式表达式。"""

    return {
        "op": "predicate",
        "predicate": "entity_state_is",
        "args": {"entity_id": entity_id, "key": key, "value": value},
    }


def entity(
    entity_id: str,
    name: str,
    description: str,
    *,
    kind: str = "object",
    location: str = "sealed_room",
    state: dict[str, Any] | None = None,
    visible_when: dict[str, Any] | None = None,
    relations: list[dict[str, str]] | None = None,
    portable: bool = False,
) -> dict[str, Any]:
    """构造 Canon Entity；可携带物只声明既有实体，不在运行时创造。"""

    payload: dict[str, Any] = {
        "id": entity_id,
        "kind": kind,
        "name": name,
        "player_visible_name": name,
        "description": description,
        "located_in": location,
        "state": state or {},
        "visibility": "public",
        "plot_relevance": True,
    }
    if relations:
        payload["relations"] = relations
    if visible_when is not None:
        payload["visibility_conditions"] = [visible_when]
    if portable:
        payload["item_component"] = {
            "portable": True,
            "unique": True,
            "quantity": 1,
        }
    return payload


def effect_step(index: int, effect: dict[str, Any], next_id: str) -> dict[str, Any]:
    """把一个权威效果包装为线性规则步骤。"""

    return {
        "id": f"success_{index}",
        "kind": "effect",
        "effect": effect,
        "next_step_id": next_id,
    }


def agent_trigger(
    families: list[str],
    location_ids: list[str],
    target_kind: str,
    target_id: str,
    option_id: str,
    hints: list[str],
) -> dict[str, Any]:
    """构造只暴露语义选项、不暴露后果的 Agent 匹配触发器。"""

    return {
        "kind": "agent_match",
        "scope": {
            "action_families": families,
            "location_ids": location_ids,
            "target_kinds": [target_kind],
            "target_ids": [target_id],
        },
        "question": {"kind": "method", "semantic_hints": hints},
        "options": [{"id": option_id, "semantic_hints": hints}],
    }


def effect_rule(
    rule_id: str,
    *,
    families: list[str],
    location_ids: list[str],
    target_kind: str,
    target_id: str,
    option_id: str,
    hints: list[str],
    effects: list[dict[str, Any]],
) -> dict[str, Any]:
    """构造无需掷骰的确定性谜题规则。"""

    steps: list[dict[str, Any]] = []
    for index, effect in enumerate(effects):
        next_id = f"success_{index + 1}" if index + 1 < len(effects) else "finish"
        steps.append(effect_step(index, effect, next_id))
    steps.append({"id": "finish", "kind": "finish"})
    return {
        "id": rule_id,
        "trigger": agent_trigger(
            families, location_ids, target_kind, target_id, option_id, hints
        ),
        "execution": {
            "branches": [{"id": option_id, "entry_step_id": "success_0"}],
            "steps": steps,
        },
    }


def check_rule(
    rule_id: str,
    *,
    families: list[str],
    target_kind: str,
    target_id: str,
    option_id: str,
    skill_id: str,
    success_effects: list[dict[str, Any]],
    failure_effects: list[dict[str, Any]],
    difficulty: str = "regular",
    hints: list[str] | None = None,
) -> dict[str, Any]:
    """构造失败后仍可重试的正式 COC7 检定规则。

    hint 必须描述玩家实际动作；未传入时才回退到技能/选项的兼容默认值。
    """

    steps: list[dict[str, Any]] = [
        {
            "id": "check",
            "kind": "check",
            "check": {
                "profile_id": "coc7.skill",
                "actor_binding": "actor",
                "initiation_kind": "active_action",
                "parameters": {"skill_id": skill_id},
                "difficulty": difficulty,
            },
            "result_routes": SUCCESS_ROUTES,
        }
    ]
    for prefix, effects in (("success", success_effects), ("failure", failure_effects)):
        for index, effect in enumerate(effects):
            next_id = f"{prefix}_{index + 1}" if index + 1 < len(effects) else "finish"
            steps.append(
                {
                    "id": f"{prefix}_{index}",
                    "kind": "effect",
                    "effect": effect,
                    "next_step_id": next_id,
                }
            )
    steps.append({"id": "finish", "kind": "finish"})
    return {
        "id": rule_id,
        "trigger": agent_trigger(
            families,
            ["sealed_room"],
            target_kind,
            target_id,
            option_id,
            hints if hints is not None else [skill_id, option_id],
        ),
        "execution": {
            "branches": [{"id": option_id, "entry_step_id": "check"}],
            "steps": steps,
        },
    }


def event_rule(
    rule_id: str,
    *,
    event_type: str,
    conditions: list[dict[str, Any]],
    steps: list[dict[str, Any]],
) -> dict[str, Any]:
    """构造由已提交状态触发的确定性事件规则。"""

    return {
        "id": rule_id,
        "trigger": {
            "kind": "event",
            "event_type": event_type,
            "when": {"op": "all", "items": conditions},
            "entry_branch_id": "default",
        },
        "execution": {
            "branches": [{"id": "default", "entry_step_id": steps[0]["id"]}],
            "steps": [*steps, {"id": "finish", "kind": "finish"}],
        },
    }


def build_module() -> dict[str, Any]:
    """生成稳定主线的完整 ModuleContentV3。"""

    info = [
        information("restraints_removed", "摆脱束缚", "调查员已用铅笔刀或床角铁皮割断绳索。", "绳索已经被割断，你恢复了行动自由。", criticality="essential"),
        information("wall_key_found", "挂画后的钥匙", "挂画后的暗格藏着上层抽屉钥匙。", "挂画后的暗格里藏着一把小钥匙。"),
        information(
            "sketchbook_found",
            "上层抽屉中的速写本",
            "暗格钥匙打开上层抽屉后，调查员发现四页速写本。前三页固定用于显现手电、钢钳和桂花糯米糖粥，第四页只能替代白纸进行通信；禁止生成清单以外的物品。",
            "你打开上层抽屉，发现里面放着一本只剩四页的速写本。书中夹着一张纸条，上面写着：“用法：撕下。请节约使用。”四张纸页分别对应手电、钢钳、桂花糯米糖粥和通信，不能用于显现其他物品。",
            criticality="essential",
        ),
        information("bed_key_found", "床下的钥匙", "移动床后可以取得中层抽屉钥匙。", "床被移开后，墙角的小钥匙终于可以拿到了。"),
        information("vent_key_found", "通风管钥匙", "手电照明可以发现通风管口的下层抽屉钥匙。", "手电光照亮管口，一把很小的钥匙卡在那里。"),
        information("flashlight_materialized", "速写本中的手电", "撕下预先画有手电的一页会显现唯一手电。", "纸页化成了一柄可以使用的手电。", criticality="essential"),
        information("cutters_materialized", "速写本中的钢钳", "固定钢钳页显现后不可再次生成。", "画中的钢钳从纸上显现出来。", criticality="essential"),
        information("porridge_materialized", "速写本中的糖粥", "固定糖粥页显现后不可再次生成。", "一碗桂花糯米糖粥从纸上显现出来。", criticality="essential"),
        information("danger_note_read", "门后的危险", "中层抽屉字条提示开门后仍有危险。", "字条写着：当你以为安全的时候，就是你最危险的时候。"),
        information("bast_contacted", "时空箱另一端的回应", "下层抽屉可与被囚的芭斯特交流。", "白纸从抽屉另一端回来，上面出现了陌生的回应。"),
        information("bast_rescued", "衣柜中的猫", "钢钳剪断锁链后救出被封住口和四肢的芭斯特。", "衣柜中被束缚的猫已经获救。", criticality="essential"),
        information("bast_trusted", "芭斯特的信任", "糖粥使芭斯特信任并跟随调查员。", "猫吃下糖粥，愿意跟在你身边。", criticality="essential"),
        information("rat_thing_seen", "通风管中的人面鼠", "人面鼠只用于正式 SAN 检定，不进入战斗。", "光束中显出一只长着微缩人脸和黄色獠牙的怪物。"),
        information("door_ghost_seen", "显示器中的虚影", "首次查看门外显示器会看见虚影并触发 SAN 检定。", "显示器里，一个模糊的鬼魂虚影正站在门外。"),
        information("captured_and_returned", "再次被抓回房间", "未获芭斯特保护时，绑架者把调查员抓回房间并重置逃脱边界。", "你再次在银色房间中醒来；已经获得的线索和工具仍在。"),
        information("silver_lock_broken", "银之锁解除", "芭斯特牺牲后法术核心消失，银锁解除。", "芭斯特扑向绑架者后倒下，束缚脚踝的力量随之消失。", criticality="essential"),
        information("kidnapper_defeated", "绑架者被击败", "调查员夺取匕首并结束绑架者威胁。", "你夺下匕首，绑架者再也无法阻止你。"),
        information("investigator_escaped", "抵达出口", "调查员在银锁解除后到达长廊外。", "你穿过透着光的门，终于逃离了银之锁的范围。", criticality="essential"),
        information("bed_search_hint", "床边的替代办法", "侦查失败不锁死主线，提示铅笔刀和锋利铁皮。", "即使没看清床下，你仍能用随身的铅笔刀处理绳索。"),
        information("bed_move_hint", "移动床的提示", "力量失败后仍允许重试或使用杠杆。", "床只是卡住了；调整受力点或借助工具仍可再次尝试。"),
        information("wardrobe_sound", "衣柜中的动静", "聆听可确认衣柜内有活物，但不是开锁前置条件。", "衣柜深处传来微弱的呻吟和沙沙声。"),
    ]

    entities = [
        entity("restraint_rope", "细绳", "捆住调查员手脚的细绳。", state={"cut": False}),
        entity("pencil_knife", "铅笔刀", "调查员醒来时仍随身带着的小刀。", portable=True),
        entity("bed", "单人床", "调查员醒来时躺着的床，床角铁皮翘起。", state={"moved": False}),
        entity("sharp_bed_corner", "锋利铁皮", "床角翘起的一片锋利铁皮。", state={"noticed": False}),
        entity("wall_painting", "猫与糖粥的挂画", "墙上的大幅挂画，无法整幅取下。", state={"inspected": False}),
        entity("wall_key", "暗格钥匙", "打开上层抽屉的钥匙。", state={"found": False}, visible_when=state_is("wall_key", "found", True), portable=True),
        entity("bed_key", "床下钥匙", "打开中层抽屉的钥匙。", state={"found": False}, visible_when=state_is("bed_key", "found", True), portable=True),
        entity("vent_key", "通风管钥匙", "打开下层抽屉的钥匙。", state={"found": False}, visible_when=state_is("vent_key", "found", True), portable=True),
        entity(
            "top_drawer",
            "上层抽屉",
            "书桌最上方的抽屉，抽屉上着锁。",
            state={"open": False},
            relations=[{"kind": "contains", "target_id": "sketchbook"}],
        ),
        entity("middle_drawer", "中层抽屉", "由床下钥匙开启。", state={"opened": False}),
        entity("bottom_drawer", "下层抽屉", "由通风管钥匙开启，是临时构建的时空箱。", state={"opened": False}),
        entity(
            "sketchbook",
            "四页速写本",
            "一本从上层抽屉中找到的速写本，只剩四页，里面夹着一张写有“用法：撕下。请节约使用。”的纸条。四页分别用于显现手电、钢钳、桂花糯米糖粥以及通信，不能显现清单之外的物品。",
            state={"discovered": False},
            visible_when=state_is("sketchbook", "discovered", True),
        ),
        entity("flashlight_page", "手电纸页", "预先画有手电的一页，撕下后显现手电。", state={"consumed": False}, visible_when=state_is("sketchbook", "discovered", True)),
        entity("cutters_page", "钢钳纸页", "固定用于显现钢钳的一页。", state={"consumed": False}, visible_when=state_is("sketchbook", "discovered", True)),
        entity("porridge_page", "糖粥纸页", "固定用于显现桂花糯米糖粥的一页。", state={"consumed": False}, visible_when=state_is("sketchbook", "discovered", True)),
        entity("communication_page", "通信纸页", "最后一页，只能替代白纸与芭斯特交流。", state={"consumed": False}, visible_when=state_is("sketchbook", "discovered", True)),
        entity("flashlight", "手电", "速写本固定显现的手电。", state={"materialized": False}, visible_when=state_is("flashlight", "materialized", True), portable=True),
        entity("bolt_cutters", "钢钳", "速写本固定显现的钢钳。", state={"materialized": False}, visible_when=state_is("bolt_cutters", "materialized", True), portable=True),
        entity("osmanthus_porridge", "桂花糯米糖粥", "速写本固定显现的一碗糖粥。", state={"materialized": False, "fed": False}, visible_when=state_is("osmanthus_porridge", "materialized", True), portable=True),
        entity("white_paper", "白纸", "中层抽屉中的通信纸。", state={"found": False, "used": False}, visible_when=state_is("white_paper", "found", True), portable=True),
        entity("vent", "通风管道", "高处的通风管道，手电能照亮管口。", state={"lit": False}),
        entity("rat_thing", "人面鼠", "藏在通风管中监视房间的怪物。", kind="npc", state={"seen": False, "san_resolved": False}, visible_when=state_is("rat_thing", "seen", True)),
        entity("wardrobe", "锁链衣柜", "把手缠着手指粗锁链的衣柜。", state={"opened": False}),
        entity("bast", "芭斯特", "被囚禁在衣柜中的猫。", kind="npc", state={"freed": False, "contacted": False, "trusted": False, "following": False, "alive": True}, visible_when=state_is("bast", "freed", True)),
        entity("door_monitor", "门外显示器", "银门旁用于观察门外的显示器。", state={"ghost_seen": False, "san_resolved": False}),
        entity("silver_door", "银白色房门", "通向长廊的金属门。", state={"opened": False}),
        entity("silver_lock", "银之锁", "以活着生灵为核心的区域束缚。", location="corridor", state={"active": True, "boundary_triggered": False}),
        entity("kidnapper", "绑架者", "持匕首接近倒地调查员的人。", kind="npc", location="corridor", state={"revealed": False, "blinded": False, "defeated": False}, visible_when=state_is("kidnapper", "revealed", True)),
        entity("dagger", "匕首", "绑架者手中的匕首。", location="corridor", state={"available": False}, visible_when=state_is("dagger", "available", True), portable=True),
    ]

    rules: list[dict[str, Any]] = []
    rules.extend(
        [
            effect_rule("cut_restraints_with_knife", families=["cut", "use"], location_ids=["sealed_room"], target_kind="entity", target_id="restraint_rope", option_id="pencil-knife", hints=["铅笔刀", "割断绳索"], effects=[{"type": "change_entity_state", "entity_id": "restraint_rope", "key": "cut", "value": True}, {"type": "reveal_information", "information_id": "restraints_removed", "scope": "party"}]),
            effect_rule("cut_restraints_on_bed_corner", families=["cut", "rub"], location_ids=["sealed_room"], target_kind="entity", target_id="sharp_bed_corner", option_id="sharp-corner", hints=["锋利铁皮", "磨断绳索"], effects=[{"type": "change_entity_state", "entity_id": "sharp_bed_corner", "key": "noticed", "value": True}, {"type": "change_entity_state", "entity_id": "restraint_rope", "key": "cut", "value": True}, {"type": "reveal_information", "information_id": "restraints_removed", "scope": "party"}]),
            check_rule("search_bed", families=["search", "observe"], target_kind="entity", target_id="bed", option_id="spot-hidden", skill_id="spot-hidden", hints=["仔细搜索床铺", "寻找床铺中的隐藏物品"], success_effects=[{"type": "change_entity_state", "entity_id": "bed_key", "key": "found", "value": True}, {"type": "reveal_information", "information_id": "bed_key_found", "scope": "party"}], failure_effects=[{"type": "reveal_information", "information_id": "bed_search_hint", "scope": "party"}]),
            check_rule("move_bed", families=["move"], target_kind="entity", target_id="bed", option_id="STR", skill_id="STR", hints=["移动床铺", "挪开床铺"], success_effects=[{"type": "change_entity_state", "entity_id": "bed", "key": "moved", "value": True}, {"type": "change_entity_state", "entity_id": "bed_key", "key": "found", "value": True}, {"type": "reveal_information", "information_id": "bed_key_found", "scope": "party"}], failure_effects=[{"type": "reveal_information", "information_id": "bed_move_hint", "scope": "party"}]),
            effect_rule("inspect_wall_painting", families=["inspect", "search"], location_ids=["sealed_room"], target_kind="entity", target_id="wall_painting", option_id="lift-painting", hints=["掀开挂画", "检查暗格"], effects=[{"type": "change_entity_state", "entity_id": "wall_painting", "key": "inspected", "value": True}, {"type": "change_entity_state", "entity_id": "wall_key", "key": "found", "value": True}, {"type": "reveal_information", "information_id": "wall_key_found", "scope": "party"}]),
            effect_rule("open_top_drawer", families=["unlock", "open"], location_ids=["sealed_room"], target_kind="entity", target_id="top_drawer", option_id="wall-key", hints=["暗格钥匙", "上层抽屉"], effects=[{"type": "change_entity_state", "entity_id": "top_drawer", "key": "open", "value": True}, {"type": "change_entity_state", "entity_id": "sketchbook", "key": "discovered", "value": True}, {"type": "reveal_information", "information_id": "sketchbook_found", "scope": "party"}]),
            effect_rule("open_middle_drawer", families=["unlock", "open"], location_ids=["sealed_room"], target_kind="entity", target_id="middle_drawer", option_id="bed-key", hints=["床下钥匙", "中层抽屉"], effects=[{"type": "change_entity_state", "entity_id": "middle_drawer", "key": "opened", "value": True}, {"type": "change_entity_state", "entity_id": "white_paper", "key": "found", "value": True}, {"type": "reveal_information", "information_id": "danger_note_read", "scope": "party"}]),
            effect_rule("materialize_flashlight", families=["tear", "use"], location_ids=["sealed_room"], target_kind="entity", target_id="flashlight_page", option_id="fixed-flashlight", hints=["撕下手电纸页"], effects=[{"type": "consume_entity", "entity_id": "flashlight_page"}, {"type": "change_entity_state", "entity_id": "flashlight", "key": "materialized", "value": True}, {"type": "reveal_information", "information_id": "flashlight_materialized", "scope": "party"}]),
            effect_rule("materialize_bolt_cutters", families=["draw", "tear"], location_ids=["sealed_room"], target_kind="entity", target_id="cutters_page", option_id="fixed-cutters", hints=["画钢钳", "撕下钢钳纸页"], effects=[{"type": "consume_entity", "entity_id": "cutters_page"}, {"type": "change_entity_state", "entity_id": "bolt_cutters", "key": "materialized", "value": True}, {"type": "reveal_information", "information_id": "cutters_materialized", "scope": "party"}]),
            effect_rule("materialize_osmanthus_porridge", families=["draw", "tear"], location_ids=["sealed_room"], target_kind="entity", target_id="porridge_page", option_id="fixed-porridge", hints=["画桂花糯米糖粥", "撕下糖粥纸页"], effects=[{"type": "consume_entity", "entity_id": "porridge_page"}, {"type": "change_entity_state", "entity_id": "osmanthus_porridge", "key": "materialized", "value": True}, {"type": "reveal_information", "information_id": "porridge_materialized", "scope": "party"}]),
            effect_rule("light_vent", families=["illuminate", "inspect"], location_ids=["sealed_room"], target_kind="entity", target_id="vent", option_id="flashlight", hints=["用手电照通风管"], effects=[{"type": "change_entity_state", "entity_id": "vent", "key": "lit", "value": True}, {"type": "change_entity_state", "entity_id": "vent_key", "key": "found", "value": True}, {"type": "change_entity_state", "entity_id": "rat_thing", "key": "seen", "value": True}, {"type": "reveal_information", "information_id": "vent_key_found", "scope": "party"}, {"type": "reveal_information", "information_id": "rat_thing_seen", "scope": "party"}]),
            effect_rule("open_bottom_drawer", families=["unlock", "open"], location_ids=["sealed_room"], target_kind="entity", target_id="bottom_drawer", option_id="vent-key", hints=["通风管钥匙", "下层抽屉"], effects=[{"type": "change_entity_state", "entity_id": "bottom_drawer", "key": "opened", "value": True}]),
            effect_rule("contact_bast_with_white_paper", families=["write", "communicate"], location_ids=["sealed_room"], target_kind="entity", target_id="white_paper", option_id="use-white-paper", hints=["把白纸放进下层抽屉"], effects=[{"type": "consume_entity", "entity_id": "white_paper"}, {"type": "change_entity_state", "entity_id": "bast", "key": "contacted", "value": True}, {"type": "reveal_information", "information_id": "bast_contacted", "scope": "party"}]),
            effect_rule("contact_bast_with_last_page", families=["write", "communicate"], location_ids=["sealed_room"], target_kind="entity", target_id="communication_page", option_id="use-last-page", hints=["用最后一页替代白纸"], effects=[{"type": "consume_entity", "entity_id": "communication_page"}, {"type": "change_entity_state", "entity_id": "bast", "key": "contacted", "value": True}, {"type": "reveal_information", "information_id": "bast_contacted", "scope": "party"}]),
            check_rule("listen_to_wardrobe", families=["listen"], target_kind="entity", target_id="wardrobe", option_id="listen", skill_id="listen", hints=["倾听衣柜", "仔细听衣柜里的动静"], success_effects=[{"type": "reveal_information", "information_id": "wardrobe_sound", "scope": "party"}], failure_effects=[{"type": "reveal_information", "information_id": "wardrobe_sound", "scope": "party"}]),
            effect_rule("cut_wardrobe_chain", families=["cut", "open"], location_ids=["sealed_room"], target_kind="entity", target_id="wardrobe", option_id="bolt-cutters", hints=["用钢钳剪开锁链"], effects=[{"type": "change_entity_state", "entity_id": "wardrobe", "key": "opened", "value": True}, {"type": "change_entity_state", "entity_id": "bast", "key": "freed", "value": True}, {"type": "reveal_information", "information_id": "bast_rescued", "scope": "party"}]),
            effect_rule("feed_bast", families=["feed", "offer"], location_ids=["sealed_room"], target_kind="entity", target_id="bast", option_id="osmanthus-porridge", hints=["喂桂花糯米糖粥"], effects=[{"type": "consume_entity", "entity_id": "osmanthus_porridge"}, {"type": "change_entity_state", "entity_id": "bast", "key": "trusted", "value": True}, {"type": "change_entity_state", "entity_id": "bast", "key": "following", "value": True}, {"type": "reveal_information", "information_id": "bast_trusted", "scope": "party"}]),
            effect_rule("inspect_door_monitor", families=["inspect", "observe"], location_ids=["sealed_room"], target_kind="entity", target_id="door_monitor", option_id="watch-monitor", hints=["查看门外显示器"], effects=[{"type": "change_entity_state", "entity_id": "door_monitor", "key": "ghost_seen", "value": True}, {"type": "reveal_information", "information_id": "door_ghost_seen", "scope": "party"}]),
            effect_rule("ask_bast_to_open_door", families=["ask", "open"], location_ids=["sealed_room"], target_kind="entity", target_id="bast", option_id="bast-opens-door", hints=["请芭斯特打开银门"], effects=[{"type": "change_entity_state", "entity_id": "silver_door", "key": "opened", "value": True}]),
            effect_rule("enter_corridor", families=["enter", "leave"], location_ids=["sealed_room"], target_kind="entity", target_id="silver_door", option_id="cross-silver-door", hints=["穿过银门进入长廊"], effects=[{"type": "enter_location", "location_id": "corridor"}, {"type": "change_entity_state", "entity_id": "silver_lock", "key": "boundary_triggered", "value": True}, {"type": "change_entity_state", "entity_id": "kidnapper", "key": "revealed", "value": True}]),
        ]
    )

    # 保护与抓回是互斥事件：只读芭斯特的权威信任状态，不让 Narrator 猜测结果。
    rules.append(event_rule("bast_breaks_silver_lock", event_type="entity.state_changed", conditions=[state_is("silver_lock", "boundary_triggered", True), state_is("bast", "trusted", True), state_is("bast", "alive", True), state_is("silver_lock", "active", True)], steps=[
        {"id": "sacrifice", "kind": "effect", "effect": {"type": "change_entity_state", "entity_id": "bast", "key": "alive", "value": False}, "next_step_id": "blind"},
        {"id": "blind", "kind": "effect", "effect": {"type": "change_entity_state", "entity_id": "kidnapper", "key": "blinded", "value": True}, "next_step_id": "dagger"},
        {"id": "dagger", "kind": "effect", "effect": {"type": "change_entity_state", "entity_id": "dagger", "key": "available", "value": True}, "next_step_id": "unlock"},
        {"id": "unlock", "kind": "effect", "effect": {"type": "change_entity_state", "entity_id": "silver_lock", "key": "active", "value": False}, "next_step_id": "reveal"},
        {"id": "reveal", "kind": "effect", "effect": {"type": "reveal_information", "information_id": "silver_lock_broken", "scope": "party"}, "next_step_id": "finish"},
    ]))
    rules.append(event_rule("kidnapper_returns_unprotected_actor", event_type="entity.state_changed", conditions=[state_is("silver_lock", "boundary_triggered", True), state_is("bast", "trusted", False), state_is("silver_lock", "active", True)], steps=[
        {"id": "close_door", "kind": "effect", "effect": {"type": "change_entity_state", "entity_id": "silver_door", "key": "opened", "value": False}, "next_step_id": "reset_boundary"},
        {"id": "reset_boundary", "kind": "effect", "effect": {"type": "change_entity_state", "entity_id": "silver_lock", "key": "boundary_triggered", "value": False}, "next_step_id": "return_room"},
        {"id": "return_room", "kind": "effect", "effect": {"type": "enter_location", "location_id": "sealed_room"}, "next_step_id": "reveal"},
        {"id": "reveal", "kind": "effect", "effect": {"type": "reveal_information", "information_id": "captured_and_returned", "scope": "party"}, "next_step_id": "finish"},
    ]))

    sanity_routes = {degree: "finish" for degree in SUCCESS_ROUTES}
    rules.append(event_rule("rat_thing_sanity", event_type="entity.state_changed", conditions=[state_is("rat_thing", "seen", True), state_is("rat_thing", "san_resolved", False)], steps=[
        {"id": "mark", "kind": "effect", "effect": {"type": "change_entity_state", "entity_id": "rat_thing", "key": "san_resolved", "value": True}, "next_step_id": "san"},
        {"id": "san", "kind": "check", "check": {"profile_id": "coc7.sanity", "actor_binding": "actor", "initiation_kind": "passive_rule", "parameters": {"success_loss": "0", "failure_loss": "1d6"}}, "result_routes": sanity_routes},
    ]))
    rules.append(event_rule("door_ghost_sanity", event_type="entity.state_changed", conditions=[state_is("door_monitor", "ghost_seen", True), state_is("door_monitor", "san_resolved", False)], steps=[
        {"id": "mark", "kind": "effect", "effect": {"type": "change_entity_state", "entity_id": "door_monitor", "key": "san_resolved", "value": True}, "next_step_id": "san"},
        {"id": "san", "kind": "check", "check": {"profile_id": "coc7.sanity", "actor_binding": "actor", "initiation_kind": "passive_rule", "parameters": {"success_loss": "1", "failure_loss": "1d3"}}, "result_routes": sanity_routes},
    ]))

    # 反击只接管玩家已选择的检定；失败保持出口开放，绝不直接声明调查员死亡。
    fight_trigger = agent_trigger(["fight", "attack", "disarm"], ["corridor"], "entity", "kidnapper", "fight-back", ["夺取匕首", "反击绑架者"])
    rules.append({
        "id": "fight_blinded_kidnapper",
        "trigger": fight_trigger,
        "execution": {
            "branches": [{"id": "fight-back", "entry_step_id": "check"}],
            "steps": [
                {"id": "check", "kind": "adjudicated_check", "adjudication_ref": "current", "effect_authority": "rule", "result_routes": SUCCESS_ROUTES, "cancel_step_id": "finish"},
                {"id": "success_0", "kind": "effect", "effect": {"type": "change_entity_state", "entity_id": "kidnapper", "key": "defeated", "value": True}, "next_step_id": "success_1"},
                {"id": "success_1", "kind": "effect", "effect": {"type": "reveal_information", "information_id": "kidnapper_defeated", "scope": "party"}, "next_step_id": "finish"},
                {"id": "failure_0", "kind": "finish"},
                {"id": "finish", "kind": "finish"},
            ],
        },
    })
    rules.append(effect_rule("escape_through_exit", families=["escape", "enter", "leave"], location_ids=["corridor"], target_kind="location", target_id="outside", option_id="escape", hints=["穿过亮门", "逃离"], effects=[
        {"type": "enter_location", "location_id": "outside"},
        {"type": "reveal_information", "information_id": "investigator_escaped", "scope": "party"},
        {"type": "mark_core_resolved"},
        {"type": "set_ending_availability", "available": True},
    ]))

    return {
        "content_schema_version": 3,
        "module_id": "silver-lock",
        "version": "3.0.1",
        "world_ref": "coc-7e",
        "background": "当代。单名调查员在昏暗的银色房间醒来，失去近期记忆且手脚被捆。叙事保持幽闭、失忆与超现实谜题交织的基调；芭斯特身份、银之锁原理、绑架者出现条件及抽屉内容在对应线索提交前不得泄露。",
        "information": info,
        "knowledge_goals": [
            {"id": "free_investigator", "target_information_ids": ["restraints_removed"], "completion": "all", "required_for_core_resolution": True},
            {"id": "obtain_fixed_tools", "target_information_ids": ["flashlight_materialized", "cutters_materialized", "porridge_materialized"], "completion": "all", "required_for_core_resolution": True},
            {"id": "rescue_and_befriend_bast", "target_information_ids": ["bast_rescued", "bast_trusted"], "completion": "all", "required_for_core_resolution": True},
            {"id": "break_silver_lock", "target_information_ids": ["silver_lock_broken"], "completion": "all", "required_for_core_resolution": True},
            {"id": "reach_exit", "target_information_ids": ["investigator_escaped"], "completion": "all", "required_for_core_resolution": True},
        ],
        "entities": entities,
        "locations": [
            {"id": "sealed_room", "kind": "room", "name": "银色房间", "player_visible_name": "银色房间", "player_visible_description": "约十平方米、墙壁刷着银漆的昏暗房间。", "plot_relevance": True, "lifecycle": "session"},
            {"id": "corridor", "kind": "connector", "name": "银锁长廊", "player_visible_name": "银白长廊", "player_visible_description": "银门外的长廊，左侧尽头有一扇透着光的门。", "plot_relevance": True, "lifecycle": "session"},
            {"id": "outside", "kind": "site", "name": "银之锁范围外", "player_visible_name": "出口之外", "player_visible_description": "银之锁失效后才能真正抵达的自由空间。", "plot_relevance": True, "lifecycle": "session"},
        ],
        "location_edges": [
            {"id": "room_to_corridor", "from_location_id": "sealed_room", "to_location_id": "corridor", "kind": "private", "traversal": "gated", "visibility": "public", "access_point_id": "silver_door", "conditions": [state_is("silver_door", "opened", True)]},
            {"id": "corridor_to_room", "from_location_id": "corridor", "to_location_id": "sealed_room", "kind": "private", "traversal": "automatic", "visibility": "public"},
            {"id": "corridor_to_outside", "from_location_id": "corridor", "to_location_id": "outside", "kind": "private", "traversal": "gated", "visibility": "public", "access_point_id": "silver_lock", "conditions": [state_is("silver_lock", "active", False)]},
        ],
        "rules": rules,
        "core_resolution": {"required_goal_ids": ["free_investigator", "obtain_fixed_tools", "rescue_and_befriend_bast", "break_silver_lock", "reach_exit"], "completion": "all"},
        "ending_policy": {"allow_continue_after_core_resolution": True, "require_no_pending_action": True, "allow_grounded_variations": True, "facets": ["investigator_fate", "kidnapper_fate", "bast_sacrifice"]},
        "ending_anchors": [
            {"id": "kill_kidnapper_then_escape", "tone": "grim", "required_fact_refs": ["silver_lock_broken", "kidnapper_defeated", "investigator_escaped"], "forbidden_claims": ["uncommitted_investigator_death", "uncommitted_hp_or_san_change"]},
            {"id": "escape_after_lock_breaks", "tone": "somber", "required_fact_refs": ["silver_lock_broken", "investigator_escaped"], "forbidden_claims": ["uncommitted_kidnapper_death", "uncommitted_investigator_death"]},
        ],
        "presentation": {
            "title": "银之锁",
            "name_en": "Silver Lock",
            "synopsis": "在昏暗的银色房间醒来后，调查员必须解开束缚、破解三把钥匙与速写本的谜题，并找到逃离银之锁的方法。",
            "players_min": 1,
            "players_max": 1,
            "difficulty": 1,
            "estimated_duration": "1-2 小时",
            "story_label": "SILVER LOCK",
            "subtitle": "银色房间中的单人逃脱",
            "authors": ["夕影"],
            "tags": ["当代", "密室逃脱", "新人向"],
            "player_intro_pages": [
                {"title": "内容提示", "content": "本模组包含绑架、拘禁、动物死亡，以及由玩家选择的致命反击。请在开始前确认这些内容适合当前参与者。"},
                {"title": "调查员准备", "content": "本模组由一名调查员进行，适合新人体验。侦查、聆听和生活常识有助于理解环境，但关键谜题均保留失败后的提示或替代路径。"},
                {"title": "醒来", "content": "你在一间昏暗的银色房间中醒来，近期记忆一片空白，手脚被细绳紧紧捆住。衣服仍完好，随身物品只剩一把铅笔刀。"},
            ],
        },
        "initial_state": {"start_location_id": "sealed_room", "default_actor_placement": {"location_id": "sealed_room"}, "start_time_point_id": "hour_12"},
        "world_profile": {"era": "当代", "region": "来历不明的封闭空间", "technology_level": "现代日常技术", "tone": "幽闭、失忆、克制的超现实恐怖", "forbidden_content": ["提前揭示芭斯特身份", "提前解释银之锁原理", "虚构调查员死亡或 HP/SAN 变化", "生成速写本固定清单以外的物品"]},
    }


def provenance(module: dict[str, Any]) -> dict[str, Any]:
    """为所有审查对象建立 DOCX 非空段落映射。"""

    mappings: dict[str, dict[str, list[int]]] = {
        "locations": {"sealed_room": [11, 13, 17, 20, 26, 45, 50, 53], "corridor": [57, 58, 60, 61, 62, 63], "outside": [57, 63]},
        "information": {},
        "rules": {},
        "knowledge_goals": {},
        "ending_anchors": {"kill_kidnapper_then_escape": [62, 63], "escape_after_lock_breaks": [62, 63]},
    }
    for item in module["information"]:
        mappings["information"][item["id"]] = [11, 63]
    for rule in module["rules"]:
        mappings["rules"][rule["id"]] = [11, 63]
    for goal in module["knowledge_goals"]:
        mappings["knowledge_goals"][goal["id"]] = [11, 63]
    # 细化关键来源，避免审查时只能看到过宽的整段范围。
    mappings["information"].update({
        "restraints_removed": [11, 12, 13, 14], "wall_key_found": [17, 18, 19], "sketchbook_found": [27, 28, 29, 30, 31, 32], "bed_key_found": [15, 16], "vent_key_found": [20, 22, 23],
        "flashlight_materialized": [30, 31, 32], "cutters_materialized": [33, 34, 48], "porridge_materialized": [33, 34, 49], "danger_note_read": [35, 36, 37, 38],
        "bast_contacted": [39, 40, 41, 42, 43], "bast_rescued": [45, 46, 47, 48], "bast_trusted": [49], "rat_thing_seen": [22, 24, 25],
        "door_ghost_seen": [50, 51], "captured_and_returned": [58, 60, 61], "silver_lock_broken": [55, 56, 58, 62, 63], "kidnapper_defeated": [60, 62, 63],
        "investigator_escaped": [57, 63], "bed_search_hint": [12, 13, 14], "bed_move_hint": [15, 16], "wardrobe_sound": [45, 46],
    })
    return {
        "_comment": "本文件记录结构化内容对应的银之锁.docx非空段落号，供人工逐项复核。",
        "source": "银之锁.docx",
        "paragraph_numbering": "解压 word/document.xml 后按非空 w:p 顺序从 1 编号",
        "module_id": module["module_id"],
        "version": module["version"],
        **mappings,
    }


def review_markdown(module: dict[str, Any], source_map: dict[str, Any]) -> str:
    """生成面向人工 Review 的覆盖矩阵与简化说明。"""

    counts = {key: len(source_map[key]) for key in ("locations", "information", "rules", "knowledge_goals", "ending_anchors")}
    return f"""<!-- 本文件说明《银之锁》结构化改编的覆盖范围、秘密隔离和运行约束。 -->
# 《银之锁》ModuleContentV3 审查报告

## 发布身份

- `module_id`: `{module['module_id']}`
- `version`: `{module['version']}`
- `world_ref`: `{module['world_ref']}`
- 原作者：夕影
- 权威来源：`银之锁.docx`
- 授权：已由发布方确认具有结构化改编和公开发布授权；合并前由人工 Reviewer 核验证据。

## 来源覆盖

| 对象 | 数量 | 已映射 |
| --- | ---: | ---: |
| Location | {len(module['locations'])} | {counts['locations']} |
| Information | {len(module['information'])} | {counts['information']} |
| Rule | {len(module['rules'])} | {counts['rules']} |
| KnowledgeGoal | {len(module['knowledge_goals'])} | {counts['knowledge_goals']} |
| EndingAnchor | {len(module['ending_anchors'])} | {counts['ending_anchors']} |

## 设计收敛

- 速写本仅允许手电、钢钳、桂花糯米糖粥三个固定产物；第四页仅可替代白纸通信。
- 人面鼠不进入战斗，不实现原文 HP 伤害；只保留正式 `coc7.sanity` 检定。
- 绑架者冲突压缩为一次 `adjudicated_check`，不实现逐轮战斗。
- 未受芭斯特保护时只重置银门与银锁边界，保留谜题进度，保证可以再次尝试。
- 结局由 EndingDraft 确认，不使用 `commit_terminal_ending`。

## 秘密隔离

- 芭斯特身份、银之锁原理、绑架者出现条件和抽屉内容仅存在于 Keeper 正文或未揭示状态。
- `presentation` 不包含谜底；内容提示只披露主题，不披露解决方法。
- Narrator 禁止虚构死亡、HP/SAN 变化、银锁解除或速写本清单外物品。

## 人工复核

- [ ] 授权凭证与公开发布范围已核验
- [ ] 每个来源段落与结构化对象逐项核对
- [ ] 双结局和失败恢复符合 Issue #348
- [ ] 真实引擎测试与前端 E2E 结果已附在 PR
"""


def main() -> None:
    """写出稳定排序、UTF-8 编码的三份审查产物。"""

    module = build_module()
    source_map = provenance(module)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "module-content-v3.json").write_text(
        json.dumps(module, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (OUTPUT_DIR / "module-content-provenance.json").write_text(
        json.dumps(source_map, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (OUTPUT_DIR / "module-content-review.md").write_text(
        review_markdown(module, source_map), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
