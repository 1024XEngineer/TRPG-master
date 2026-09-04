"""生成《常暗之厢》的可发布 ModuleContentV3 与审查产物。

原文允许 KP 用逐车厢行动次数制造追逐压力，但当前 Runtime 没有可靠的行动计数器。
这里把该可选机制 lower 为 23:00 到次日 00:00 的世界时间终点；自由战斗、对抗检定、
固定 SAN 损失与技能百分比修正只记录为 capability gap，不用叙事冒充权威状态。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from collaboration_framework.contracts import ModuleContentV3
from collaboration_framework.engine import audit_runtime_capabilities
from collaboration_framework.module import validate_module_v3

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = (
    ROOT
    / "docs"
    / "module-parser"
    / "examples"
    / "module-content-validation"
    / "常暗之厢"
)

SUCCESS_DEGREES = (
    "critical_success",
    "extreme_success",
    "hard_success",
    "regular_success",
)


def result_routes(difficulty: str) -> dict[str, str]:
    """按 CoC 7e 成功等级把不足难度的结果送入失败分支。"""

    required = {"regular": 4, "hard": 3, "extreme": 2}[difficulty]
    routes = {
        degree: "success_0" if index < required else "failure_0"
        for index, degree in enumerate(SUCCESS_DEGREES)
    }
    return {**routes, "failure": "failure_0", "fumble": "failure_0"}


def information(
    item_id: str,
    title: str,
    keeper: str,
    player: str,
    *,
    kind: str = "fact",
    criticality: str = "supporting",
    recovery: str = "adaptive",
) -> dict[str, Any]:
    """建立 Keeper / Player 严格分离的 Canon Information。"""

    return {
        "id": item_id,
        "kind": kind,
        "title": title,
        "keeper_content": keeper,
        "player_content": player,
        "criticality": criticality,
        "recovery": {
            "policy": recovery,
            "allowed_source_types": ["explicit_entity", "explicit_location"],
        },
    }


def state_is(entity_id: str, key: str, value: Any) -> dict[str, Any]:
    return {
        "op": "predicate",
        "predicate": "entity_state_is",
        "args": {"entity_id": entity_id, "key": key, "value": value},
    }


def information_is(item_id: str) -> dict[str, Any]:
    return {
        "op": "predicate",
        "predicate": "information_is",
        "args": {"id": item_id},
    }


def party_location_is(location_id: str) -> dict[str, Any]:
    return {
        "op": "predicate",
        "predicate": "party_location_is",
        "args": {"id": location_id},
    }


def time_point_is(point_id: str) -> dict[str, Any]:
    return {
        "op": "predicate",
        "predicate": "time_point_is",
        "args": {"value": point_id},
    }


def days_elapsed_at_least(value: int) -> dict[str, Any]:
    return {
        "op": "predicate",
        "predicate": "days_elapsed_at_least",
        "args": {"value": value},
    }


def core_resolved(value: bool) -> dict[str, Any]:
    return {
        "op": "predicate",
        "predicate": "core_resolved",
        "args": {"value": value},
    }


def all_of(*items: dict[str, Any]) -> dict[str, Any]:
    return items[0] if len(items) == 1 else {"op": "all", "items": list(items)}


def any_of(*items: dict[str, Any]) -> dict[str, Any]:
    return items[0] if len(items) == 1 else {"op": "any", "items": list(items)}


def reveal(item_id: str) -> dict[str, Any]:
    return {"type": "reveal_information", "information_id": item_id, "scope": "party"}


def set_state(entity_id: str, key: str, value: Any) -> dict[str, Any]:
    return {
        "type": "change_entity_state",
        "entity_id": entity_id,
        "key": key,
        "value": value,
    }


def entity(
    entity_id: str,
    name: str,
    player_name: str,
    description: str,
    *,
    location: str,
    kind: str = "object",
    state: dict[str, Any] | None = None,
    visible_when: list[dict[str, Any]] | None = None,
    visibility: str = "public",
    portable: bool = False,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": entity_id,
        "kind": kind,
        "name": name,
        "player_visible_name": player_name,
        "description": description,
        "located_in": location,
        "state": state or {},
        "visibility": visibility,
        "plot_relevance": True,
        "lifecycle": "session",
    }
    if visible_when:
        payload["visibility_conditions"] = visible_when
    if portable:
        payload["item_component"] = {"portable": True, "unique": True, "quantity": 1}
        payload["initial_custody"] = {"kind": "location"}
    return payload


def agent_trigger(
    families: list[str],
    locations: list[str],
    target_kind: str,
    target_id: str,
    option_id: str,
    hints: list[str],
    *,
    when: dict[str, Any] | None = None,
    question_kind: str = "method",
) -> dict[str, Any]:
    semantic_hints = list(
        dict.fromkeys(
            hint.strip()
            for hint in hints
            if hint.strip() and hint.strip() not in {*families, option_id}
        )
    )
    trigger: dict[str, Any] = {
        "kind": "agent_match",
        "required": True,
        "decision_mode": "selective",
        "scope": {
            "action_families": families,
            "location_ids": locations,
            "target_kinds": [target_kind],
            "target_ids": [target_id],
        },
        "question": {"kind": question_kind, "semantic_hints": semantic_hints},
        "options": [{"id": option_id, "semantic_hints": semantic_hints}],
    }
    if when is not None:
        trigger["when"] = when
    return trigger


def effect_steps(
    effects: list[dict[str, Any]], *, prefix: str = "effect"
) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
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
    return steps


def effect_rule(
    rule_id: str,
    *,
    families: list[str],
    locations: list[str],
    target_kind: str,
    target_id: str,
    option_id: str,
    hints: list[str],
    effects: list[dict[str, Any]],
    when: dict[str, Any] | None = None,
    priority: int = 0,
    question_kind: str = "method",
) -> dict[str, Any]:
    return {
        "id": rule_id,
        "priority": priority,
        "trigger": agent_trigger(
            families,
            locations,
            target_kind,
            target_id,
            option_id,
            hints,
            when=when,
            question_kind=question_kind,
        ),
        "execution": {
            "branches": [{"id": option_id, "entry_step_id": "effect_0"}],
            "steps": [*effect_steps(effects), {"id": "finish", "kind": "finish"}],
        },
    }


def check_rule(
    rule_id: str,
    *,
    families: list[str],
    locations: list[str],
    target_kind: str,
    target_id: str,
    option_id: str,
    hints: list[str],
    skill_id: str,
    success_effects: list[dict[str, Any]],
    failure_effects: list[dict[str, Any]],
    when: dict[str, Any] | None = None,
    difficulty: str = "regular",
    priority: int = 0,
) -> dict[str, Any]:
    success_steps = effect_steps(success_effects, prefix="success")
    failure_steps = effect_steps(failure_effects, prefix="failure")
    routes = result_routes(difficulty)
    if not success_effects:
        routes = {
            degree: "finish" if target == "success_0" else target
            for degree, target in routes.items()
        }
    if not failure_effects:
        routes = {
            degree: "finish" if target == "failure_0" else target
            for degree, target in routes.items()
        }
    return {
        "id": rule_id,
        "priority": priority,
        "trigger": agent_trigger(
            families,
            locations,
            target_kind,
            target_id,
            option_id,
            hints,
            when=when,
        ),
        "execution": {
            "branches": [{"id": option_id, "entry_step_id": "check"}],
            "steps": [
                {
                    "id": "check",
                    "kind": "check",
                    "check": {
                        "profile_id": "coc7.skill",
                        "actor_binding": "actor",
                        "initiation_kind": "active_action",
                        "parameters": {"skill_id": skill_id},
                        "difficulty": difficulty,
                        "allow_luck": True,
                        "allow_push": True,
                    },
                    "result_routes": routes,
                },
                *success_steps,
                *failure_steps,
                {"id": "finish", "kind": "finish"},
            ],
        },
    }


def event_rule(
    rule_id: str,
    *,
    event_type: str,
    conditions: list[dict[str, Any]],
    effects: list[dict[str, Any]],
    priority: int = 0,
) -> dict[str, Any]:
    return {
        "id": rule_id,
        "priority": priority,
        "trigger": {
            "kind": "event",
            "event_type": event_type,
            "when": all_of(*conditions),
            "entry_branch_id": "default",
        },
        "execution": {
            "branches": [{"id": "default", "entry_step_id": "effect_0"}],
            "steps": [*effect_steps(effects), {"id": "finish", "kind": "finish"}],
        },
    }


def sanity_event_rule(
    rule_id: str,
    *,
    information_id: str,
    marker_key: str,
    success_loss: str,
    failure_loss: str,
) -> dict[str, Any]:
    routes = {degree: "finish" for degree in (*SUCCESS_DEGREES, "failure", "fumble")}
    return {
        "id": rule_id,
        "trigger": {
            "kind": "event",
            "event_type": "information.revealed",
            "when": all_of(
                information_is(information_id),
                state_is("horror_checks", marker_key, False),
            ),
            "entry_branch_id": "default",
        },
        "execution": {
            "branches": [{"id": "default", "entry_step_id": "mark"}],
            "steps": [
                {
                    "id": "mark",
                    "kind": "effect",
                    "effect": set_state("horror_checks", marker_key, True),
                    "next_step_id": "san",
                },
                {
                    "id": "san",
                    "kind": "check",
                    "check": {
                        "profile_id": "coc7.sanity",
                        "actor_binding": "actor",
                        "initiation_kind": "passive_rule",
                        "parameters": {
                            "success_loss": success_loss,
                            "failure_loss": failure_loss,
                        },
                    },
                    "result_routes": routes,
                },
                {"id": "finish", "kind": "finish"},
            ],
        },
    }


def build_information() -> list[dict[str, Any]]:
    return [
        information(
            "warning_note_front",
            "车门上的便签",
            "6 号车厢门上的便签正面写着只能前进、没有退路。",
            "便签上写着：“只管前进吧，已经没有退路了。”",
        ),
        information(
            "warning_note_back",
            "便签背面的钥匙提示",
            "便签背面明确提示第三个箱子，即 3 号车厢里藏着钥匙。",
            "便签背面写着：“第三个箱子里藏着钥匙。”结合车厢编号，这指向 3 号车厢。",
            criticality="essential",
            recovery="strict",
        ),
        information(
            "route_map_erased",
            "被涂掉的列车图",
            "门旁示意图中 7 号车厢以后的部分被人蓄意涂掉。",
            "门旁的示意图并非自然磨损：7 号车厢之后的部分像是被人故意涂掉了。",
        ),
        information(
            "rear_car_bodies",
            "7 号车厢的残肢",
            "打开 7 号车厢后会看见不久前被撕裂的人体残肢。",
            "7 号车厢里散落着被撕裂的人体残肢，血腥味仍然浓重。",
        ),
        information(
            "death_was_recent",
            "死亡时间不久",
            "医学检查确认车厢里的死者死亡时间并不久。",
            "医学检查显示，这些人死亡至今并没有多久。",
        ),
        information(
            "rear_maw_seen",
            "吞噬车厢的巨大存在",
            "7 号车厢深处的大嘴属于一个比整列电车更巨大的存在；修正版将其设定为奈亚化身。",
            "车厢深处有一张巨大得不合常理的嘴正在啃蚀列车；它属于某个比电车还要庞大的存在。",
        ),
        information(
            "newspaper_report",
            "末班车恐怖事件报道",
            "5 号车厢的报纸报道昨晚本线末班车发生恐怖事件，幸存者全部精神失常。",
            "报纸报道：昨晚这条线路的末班车发生大规模恐怖事件，幸存乘客因精神极度异常被送医。",
            kind="record",
        ),
        information(
            "newspaper_from_tomorrow",
            "来自第二天的报纸",
            "报纸日期是第二天，报道的正是调查员正在经历的事件；修正版据此建立梦境因果。",
            "这张报纸的日期竟然是第二天，而报道内容正与眼前发生的事情相符。",
            criticality="essential",
            kind="record",
        ),
        information(
            "attendant_attack_account",
            "乘务员的袭击经历",
            "京山人吉称类人的怪物逐个撕咬乘客，他逃跑时腿部被咬伤。",
            "乘务员说，像人一样的怪物突然袭击乘客；他在逃跑时腿部也被咬伤。",
            kind="testimony",
        ),
        information(
            "clickers_follow_sound",
            "怪物对声音敏感",
            "乘务员回忆自己甩出的物品撞墙后吸引了怪物，证明循声者极端依赖声音。",
            "乘务员回忆：被咬时，他把手边的东西甩到墙上，撞击声立刻吸引了怪物。它们似乎对声音极其敏感。",
            criticality="essential",
            kind="testimony",
            recovery="guaranteed",
        ),
        information(
            "key_bag_location",
            "黑色钥匙包的位置",
            "乘务员的驾驶室钥匙与控制面板钥匙装在断带黑包里，约掉在 3 号车厢前门附近。",
            "驾驶室钥匙和控制面板钥匙都在一个背带断掉的黑包里；乘务员记得它大约掉在 3 号车厢前门附近。",
            criticality="essential",
            kind="testimony",
            recovery="guaranteed",
        ),
        information(
            "key_bag_retrieved",
            "两把钥匙已经取回",
            "调查员已经取得黑包中的驾驶室钥匙和控制面板钥匙。",
            "你已经拿到黑包里的两把钥匙：一把开驾驶室，一把开控制面板。",
            criticality="essential",
            recovery="strict",
        ),
        information(
            "key_search_can_continue",
            "杂乱行李仍可继续搜索",
            "侦查失败不关闭唯一钥匙路径；原文允许继续探索，且已知位置提供有利修正。",
            "行李太杂乱，这次没找到；调整搜索范围后仍然可以继续找。",
        ),
        information(
            "clickers_alerted",
            "脚步声惊动了怪物",
            "潜行失败使循声者注意到调查员，但原文允许用更大的持续声响转移它们。",
            "你踩中了地上的残骸，黑暗中的喘息声立刻转向这里；更远、更大的声音仍可能把它们引开。",
        ),
        information(
            "clicker_car_crossed",
            "已经通过 2 号车厢",
            "调查员以潜行或制造声响通过循声者所在车厢并抵达先头车厢。",
            "你们已经越过黑暗中的怪物，抵达先头车厢。",
            criticality="essential",
        ),
        information(
            "control_panel_instructions",
            "列车控制杆的作用",
            "左杆控制刹车与起步；右杆向下加速、向上减速。",
            "控制面板上有两只拉杆：左杆控制刹车与起步；右杆向下拉是加速，向上拉是减速。",
            criticality="essential",
        ),
        information(
            "carry_attempt_can_retry",
            "可以调整姿势再搬运",
            "搬运检定失败不会杀死乘务员或关闭主线；可调整姿势后重试，也可把他留在 4 号车厢。",
            "乘务员伤得很重，这次没能稳妥背起他；你可以调整姿势再试，或让他留在这里。",
        ),
        information(
            "first_aid_can_retry",
            "乘务员仍可继续救治",
            "7 版修正明确要求乘务员只是重伤而非因一次急救失败死亡，主线必须允许继续急救。",
            "这次处理没能让乘务员醒来，但他的状况尚未恶化，仍可以调整方法继续急救。",
        ),
        information(
            "attendant_requests_key_custody",
            "乘务员想保管钥匙",
            "乘务员找到黑包后希望自己承担责任并保管钥匙；说服失败不会永久关闭再次交涉。",
            "乘务员坚持自己应该保管钥匙，但仍可以继续与他交涉。",
            kind="testimony",
        ),
        information(
            "ending_accelerate",
            "列车加速后的清醒",
            "调查员把列车加速到极致后被白光覆盖，在现实的 6 号车厢醒来并抵达终点站。",
            "你把列车加速到极致。刺眼白光过后，你在现实的 6 号车厢醒来；广播正通知终点站已经到达。",
            criticality="essential",
        ),
        information(
            "ending_decelerate",
            "列车减速后的噩梦余波",
            "调查员减速停车后在梦中被吞噬，随后从电车座位醒来，并发现断带黑包仍在身边。",
            "列车减速后，黑暗与咀嚼声吞没了一切。你从电车座位惊醒，断带黑包仍在身边，那段恐惧却挥之不去。",
            criticality="essential",
        ),
        information(
            "ending_consumed",
            "未能逃离的疯狂结局",
            "到达午夜终点仍未解决列车危机时，大嘴吞没梦境；修正版结局 C 规定调查员在现实中陷入极度疯狂并被送医。",
            "午夜到来时，大嘴吞没了残余车厢。现实中的你们在极度恐惧中醒来，随后因持续的疯狂状态被送医。",
            criticality="essential",
        ),
    ]


def build_entities() -> list[dict[str, Any]]:
    return [
        entity(
            "train_chase",
            "梦境列车追逐状态",
            "",
            "列车与大嘴之间的权威追逐状态。",
            location="car_7",
            visibility="keeper",
            state={"active": True, "deadline_reached": False, "outcome": "none"},
        ),
        entity(
            "horror_checks",
            "恐怖检定结算标记",
            "",
            "保证每类原文恐怖场景只请求一次被动理智检定。",
            location="dream_train",
            visibility="keeper",
            state={"bodies": False, "maw": False},
        ),
        entity(
            "warning_note",
            "车门便签",
            "车门上的便签",
            "贴在 6 号车厢前门上的便签。",
            location="car_6",
            state={"read": False, "back_seen": False},
        ),
        entity(
            "route_map",
            "列车示意图",
            "列车示意图",
            "画在车门旁的列车车厢示意图。",
            location="car_6",
            state={"inspected": False},
        ),
        entity(
            "rear_door",
            "通往 7 号车厢的门",
            "通往 7 号车厢的门",
            "6 号车厢后方的车门，门缝里透出血腥味。",
            location="car_6",
            state={"opened": False},
        ),
        entity(
            "rear_car_horror",
            "7 号车厢残骸",
            "散落的残骸",
            "7 号车厢内散落的血迹和人体残肢。",
            location="car_7",
            state={"seen": False},
            visible_when=[state_is("rear_car_horror", "seen", True)],
        ),
        entity(
            "rear_maw",
            "奈亚化身的大嘴",
            "吞噬列车的巨大存在",
            "从车尾向前吞噬列车、比整列电车更庞大的嘴状存在。",
            location="car_7",
            kind="npc",
            state={"revealed": False, "active": True, "reached_party": False},
            visible_when=[
                all_of(
                    state_is("rear_maw", "revealed", True),
                    state_is("rear_maw", "active", True),
                )
            ],
        ),
        entity(
            "newspaper",
            "来自次日的报纸",
            "掉在座位下的报纸",
            "5 号车厢里的一张报纸。",
            location="car_5",
            state={"found": False, "date_understood": False},
            visible_when=[state_is("newspaper", "found", True)],
        ),
        entity(
            "attendant",
            "京山人吉",
            "重伤的乘务员",
            "腿部有咬伤、处于休克状态的 30 岁男性乘务员。",
            location="car_4",
            kind="npc",
            state={
                "present": True,
                "awake": False,
                "attack_told": False,
                "sound_weakness_told": False,
                "key_location_told": False,
                "accompanying": False,
                "maw_believed": False,
                "allows_acceleration": False,
            },
            visible_when=[state_is("attendant", "present", True)],
        ),
        entity(
            "luggage_pile",
            "散乱行李",
            "散乱的行李",
            "堆满 3 号车厢、会妨碍奔跑和搜索的行李。",
            location="car_3",
            state={"passage_cleared": False},
        ),
        entity(
            "key_bag",
            "断带黑包与两把钥匙",
            "背带断掉的黑色包",
            "装有驾驶室钥匙和控制面板钥匙的黑色包。",
            location="car_3",
            state={"found": False, "retrieved": False, "carried": False},
            visible_when=[state_is("key_bag", "found", True)],
        ),
        entity(
            "car_2_door",
            "2 号车厢前门",
            "通往黑暗车厢的门",
            "从 3 号车厢望向 2 号车厢的门，玻璃后一片漆黑。",
            location="car_3",
            state={"crossing_resolved": False},
        ),
        entity(
            "clicker_group",
            "循声者群",
            "黑暗中的无眼怪物",
            "潜伏在 2 号车厢、没有视力且对声音极其敏感的类人生物。",
            location="car_2",
            kind="npc",
            state={
                "noticed": False,
                "alerted": False,
                "distracted": False,
                "active": True,
            },
            visible_when=[
                all_of(
                    state_is("clicker_group", "noticed", True),
                    state_is("clicker_group", "active", True),
                )
            ],
        ),
        entity(
            "cab_door",
            "驾驶室门",
            "通往驾驶室的门",
            "先头车厢最前端上锁的驾驶室门。",
            location="lead_car",
            state={"opened": False},
        ),
        entity(
            "control_panel",
            "列车控制面板",
            "列车控制面板",
            "有左右两只拉杆的列车控制面板。",
            location="driver_cab",
            state={"unlocked": False, "inspected": False, "lever": "neutral"},
        ),
    ]


def build_rules() -> list[dict[str, Any]]:
    no_outcome = all_of(
        state_is("train_chase", "outcome", "none"),
        core_resolved(False),
    )
    rules: list[dict[str, Any]] = [
        effect_rule(
            "read_warning_note",
            families=["read", "inspect"],
            locations=["car_6"],
            target_kind="entity",
            target_id="warning_note",
            option_id="read-front",
            hints=["读门上的便签", "看看便签写了什么", "查看车门纸条"],
            when=state_is("warning_note", "read", False),
            effects=[
                set_state("warning_note", "read", True),
                reveal("warning_note_front"),
            ],
        ),
        effect_rule(
            "turn_warning_note_over",
            families=["inspect", "turn-over", "remove"],
            locations=["car_6"],
            target_kind="entity",
            target_id="warning_note",
            option_id="inspect-back",
            hints=[
                "把便签翻到背面",
                "撕下便签看看背后",
                "检查纸条背面",
                "我把便签撕下来翻到背面看看",
            ],
            when=all_of(
                state_is("warning_note", "read", True),
                state_is("warning_note", "back_seen", False),
            ),
            effects=[
                set_state("warning_note", "back_seen", True),
                reveal("warning_note_back"),
            ],
        ),
        check_rule(
            "inspect_route_map",
            families=["inspect", "observe"],
            locations=["car_6"],
            target_kind="entity",
            target_id="route_map",
            option_id="notice-erasure",
            hints=["仔细看列车示意图", "检查车厢地图", "看看地图哪里被涂掉"],
            skill_id="idea",
            when=state_is("route_map", "inspected", False),
            success_effects=[
                set_state("route_map", "inspected", True),
                reveal("route_map_erased"),
            ],
            failure_effects=[],
        ),
        effect_rule(
            "enter_rear_car",
            families=["open", "enter", "explore"],
            locations=["car_6"],
            target_kind="entity",
            target_id="rear_door",
            option_id="open-and-enter",
            hints=["打开后门进入7号车厢", "去后面的7号车厢", "顶着血腥味开门"],
            when=all_of(no_outcome, state_is("rear_door", "opened", False)),
            effects=[
                set_state("rear_door", "opened", True),
                {"type": "enter_location", "location_id": "car_7"},
                set_state("rear_car_horror", "seen", True),
                reveal("rear_car_bodies"),
            ],
        ),
        check_rule(
            "examine_rear_car_bodies",
            families=["examine", "medical", "inspect"],
            locations=["car_7"],
            target_kind="entity",
            target_id="rear_car_horror",
            option_id="estimate-death-time",
            hints=["检查残肢的死亡时间", "用医学查看尸体", "判断这些人死了多久"],
            skill_id="medicine",
            when=state_is("rear_car_horror", "seen", True),
            success_effects=[reveal("death_was_recent")],
            failure_effects=[],
        ),
        check_rule(
            "spot_rear_maw",
            families=["observe", "inspect", "look"],
            locations=["car_7"],
            target_kind="location",
            target_id="car_7",
            option_id="look-into-darkness",
            hints=["观察7号车厢深处", "看看黑暗里是什么", "寻找吞噬车厢的东西"],
            skill_id="spot-hidden",
            when=state_is("rear_maw", "revealed", False),
            success_effects=[
                set_state("rear_maw", "revealed", True),
                reveal("rear_maw_seen"),
            ],
            failure_effects=[],
        ),
        check_rule(
            "search_newspaper",
            families=["search", "inspect"],
            locations=["car_5"],
            target_kind="location",
            target_id="car_5",
            option_id="find-newspaper",
            hints=["搜索5号车厢", "找找座位附近的报纸", "仔细查看第五节车厢"],
            skill_id="spot-hidden",
            when=state_is("newspaper", "found", False),
            success_effects=[
                set_state("newspaper", "found", True),
                reveal("newspaper_report"),
            ],
            failure_effects=[],
        ),
        check_rule(
            "analyze_newspaper_date",
            families=["read", "research", "inspect"],
            locations=["car_5"],
            target_kind="entity",
            target_id="newspaper",
            option_id="compare-date-and-report",
            hints=["翻看报纸日期", "核对报纸报道和现在", "仔细阅读这张报纸"],
            skill_id="library-use",
            when=all_of(
                state_is("newspaper", "found", True),
                state_is("newspaper", "date_understood", False),
            ),
            success_effects=[
                set_state("newspaper", "date_understood", True),
                reveal("newspaper_from_tomorrow"),
            ],
            failure_effects=[],
        ),
        check_rule(
            "first_aid_attendant",
            families=["first-aid", "help", "treat"],
            locations=["car_4"],
            target_kind="entity",
            target_id="attendant",
            option_id="wake-attendant",
            hints=[
                "给重伤乘务员急救",
                "处理乘务员腿上的伤",
                "设法让乘务员清醒",
                "我先给重伤的乘务员做急救",
            ],
            skill_id="first-aid",
            when=all_of(
                state_is("attendant", "present", True),
                state_is("attendant", "awake", False),
            ),
            success_effects=[set_state("attendant", "awake", True)],
            failure_effects=[reveal("first_aid_can_retry")],
        ),
        effect_rule(
            "ask_attendant_about_attack",
            families=["ask", "interview", "talk"],
            locations=["car_4"],
            target_kind="entity",
            target_id="attendant",
            option_id="ask-what-happened",
            hints=["问乘务员发生了什么", "询问他为什么受伤", "让乘务员讲述袭击"],
            when=all_of(
                state_is("attendant", "awake", True),
                state_is("attendant", "attack_told", False),
            ),
            effects=[
                set_state("attendant", "attack_told", True),
                reveal("attendant_attack_account"),
            ],
        ),
        effect_rule(
            "ask_attendant_about_attackers",
            families=["ask", "question", "talk"],
            locations=["car_4"],
            target_kind="entity",
            target_id="attendant",
            option_id="ask-attacker-features",
            hints=["追问袭击者的特征", "问怪物有什么弱点", "让乘务员讲清楚怪物反应"],
            when=all_of(
                state_is("attendant", "attack_told", True),
                state_is("attendant", "sound_weakness_told", False),
            ),
            effects=[
                set_state("attendant", "sound_weakness_told", True),
                reveal("clickers_follow_sound"),
            ],
        ),
        effect_rule(
            "ask_attendant_about_keys",
            families=["ask", "question", "talk"],
            locations=["car_4"],
            target_kind="entity",
            target_id="attendant",
            option_id="ask-key-location",
            hints=["问驾驶室钥匙在哪里", "询问黑色包掉在哪里", "追问两把钥匙的位置"],
            when=all_of(
                state_is("attendant", "awake", True),
                state_is("attendant", "key_location_told", False),
            ),
            effects=[
                set_state("attendant", "key_location_told", True),
                reveal("key_bag_location"),
            ],
        ),
        check_rule(
            "carry_attendant_to_car_3",
            families=["carry", "help", "travel"],
            locations=["car_4"],
            target_kind="entity",
            target_id="attendant",
            option_id="carry-forward",
            hints=["背起乘务员去3号车厢", "扶着受伤乘务员继续前进", "把乘务员一起带走"],
            skill_id="STR",
            when=all_of(
                state_is("attendant", "awake", True),
                state_is("attendant", "accompanying", False),
                no_outcome,
            ),
            success_effects=[
                set_state("attendant", "accompanying", True),
                {
                    "type": "move_entity",
                    "entity_id": "attendant",
                    "location_id": "car_3",
                },
                {"type": "enter_location", "location_id": "car_3"},
                set_state("key_bag", "found", True),
                reveal("key_bag_location"),
            ],
            failure_effects=[reveal("carry_attempt_can_retry")],
        ),
        check_rule(
            "search_key_bag",
            families=["search", "inspect"],
            locations=["car_3"],
            target_kind="entity",
            target_id="luggage_pile",
            option_id="search-front-door-luggage",
            hints=[
                "在3号车厢前门附近找黑包",
                "翻找散乱行李里的钥匙",
                "搜索第三节车厢的断带包",
                "我在3号车厢前门附近翻找那个断带黑包",
            ],
            skill_id="spot-hidden",
            when=all_of(
                state_is("key_bag", "retrieved", False),
                state_is("attendant", "accompanying", False),
                no_outcome,
            ),
            success_effects=[
                set_state("key_bag", "found", True),
                set_state("key_bag", "retrieved", True),
                set_state("key_bag", "carried", True),
                reveal("key_bag_retrieved"),
            ],
            failure_effects=[reveal("key_search_can_continue")],
        ),
        check_rule(
            "persuade_attendant_to_hand_over_keys",
            families=["persuade", "talk", "request"],
            locations=["car_3"],
            target_kind="entity",
            target_id="attendant",
            option_id="keep-key-bag",
            hints=[
                "说服乘务员把钥匙交给我",
                "劝他让我保管黑包",
                "请求自己拿着两把钥匙",
            ],
            skill_id="persuade",
            when=all_of(
                state_is("attendant", "accompanying", True),
                state_is("key_bag", "found", True),
                state_is("key_bag", "retrieved", False),
                no_outcome,
            ),
            success_effects=[
                set_state("key_bag", "retrieved", True),
                set_state("key_bag", "carried", True),
                reveal("key_bag_retrieved"),
            ],
            failure_effects=[reveal("attendant_requests_key_custody")],
        ),
        check_rule(
            "observe_car_2_through_glass",
            families=["observe", "inspect", "listen"],
            locations=["car_3"],
            target_kind="entity",
            target_id="car_2_door",
            option_id="watch-dark-car",
            hints=["透过门玻璃观察2号车厢", "听黑暗里的喘息声", "看看前面有几个怪物"],
            skill_id="spot-hidden",
            when=state_is("clicker_group", "noticed", False),
            success_effects=[set_state("clicker_group", "noticed", True)],
            failure_effects=[],
        ),
        check_rule(
            "sneak_past_clickers",
            families=["sneak", "cross", "enter"],
            locations=["car_3"],
            target_kind="entity",
            target_id="clicker_group",
            option_id="move-silently",
            hints=["蹑手蹑脚通过2号车厢", "悄悄绕过循声怪物", "不出声地潜行到先头车厢"],
            skill_id="stealth",
            when=all_of(
                state_is("car_2_door", "crossing_resolved", False),
                no_outcome,
            ),
            success_effects=[
                set_state("car_2_door", "crossing_resolved", True),
                {"type": "enter_location", "location_id": "lead_car"},
                reveal("clicker_car_crossed"),
            ],
            failure_effects=[
                set_state("clicker_group", "alerted", True),
                reveal("clickers_alerted"),
            ],
        ),
        effect_rule(
            "distract_clickers_and_pass",
            families=["distract", "throw", "cross"],
            locations=["car_3"],
            target_kind="entity",
            target_id="clicker_group",
            option_id="make-distant-noise",
            hints=[
                "把东西扔远制造声音",
                "用持续声响引开怪物",
                "趁循声者追声音时通过",
                "我把东西扔远制造声音，趁怪物被引开时通过",
            ],
            when=all_of(
                state_is("car_2_door", "crossing_resolved", False),
                any_of(
                    information_is("clickers_follow_sound"),
                    state_is("clicker_group", "alerted", True),
                ),
                no_outcome,
            ),
            effects=[
                set_state("clicker_group", "distracted", True),
                set_state("clicker_group", "alerted", False),
                set_state("car_2_door", "crossing_resolved", True),
                {"type": "enter_location", "location_id": "lead_car"},
                reveal("clicker_car_crossed"),
            ],
            priority=100,
        ),
        effect_rule(
            "unlock_cab_and_panel",
            families=["unlock", "open", "enter"],
            locations=["lead_car"],
            target_kind="entity",
            target_id="cab_door",
            option_id="use-both-keys",
            hints=[
                "用两把钥匙打开驾驶室和面板",
                "开驾驶室门进入控制室",
                "拿钥匙解锁列车控制台",
            ],
            when=all_of(
                state_is("key_bag", "retrieved", True),
                state_is("cab_door", "opened", False),
                no_outcome,
            ),
            effects=[
                set_state("cab_door", "opened", True),
                set_state("control_panel", "unlocked", True),
                {"type": "enter_location", "location_id": "driver_cab"},
            ],
        ),
        effect_rule(
            "inspect_control_panel",
            families=["inspect", "learn", "operate"],
            locations=["driver_cab"],
            target_kind="entity",
            target_id="control_panel",
            option_id="identify-levers",
            hints=[
                "观察两只控制杆的作用",
                "弄清列车怎么加速减速",
                "检查驾驶室控制面板",
            ],
            when=all_of(
                state_is("control_panel", "unlocked", True),
                state_is("control_panel", "inspected", False),
                no_outcome,
            ),
            effects=[
                set_state("control_panel", "inspected", True),
                reveal("control_panel_instructions"),
            ],
        ),
        check_rule(
            "persuade_attendant_to_allow_acceleration",
            families=["persuade", "explain", "talk"],
            locations=["driver_cab"],
            target_kind="entity",
            target_id="attendant",
            option_id="keep-train-moving",
            hints=["说服乘务员不要停车", "劝他相信后面有大嘴", "让乘务员同意继续加速"],
            skill_id="persuade",
            when=all_of(
                state_is("attendant", "accompanying", True),
                state_is("attendant", "allows_acceleration", False),
                no_outcome,
            ),
            success_effects=[
                set_state("attendant", "maw_believed", True),
                set_state("attendant", "allows_acceleration", True),
            ],
            failure_effects=[],
        ),
    ]

    rules.extend(
        [
            effect_rule(
                "accelerate_train",
                families=["accelerate", "operate", "escape"],
                locations=["driver_cab"],
                target_kind="entity",
                target_id="control_panel",
                option_id="push-throttle-down",
                hints=[
                    "把右侧油门杆向下拉到底",
                    "让列车全速加速",
                    "不停车继续冲向前方",
                    "我把右边的油门杆向下拉到底，让列车全速加速",
                ],
                question_kind="action_declaration",
                priority=200,
                when=all_of(
                    state_is("key_bag", "retrieved", True),
                    state_is("car_2_door", "crossing_resolved", True),
                    state_is("control_panel", "unlocked", True),
                    state_is("control_panel", "inspected", True),
                    any_of(
                        state_is("attendant", "accompanying", False),
                        state_is("attendant", "maw_believed", True),
                        state_is("attendant", "allows_acceleration", True),
                    ),
                    no_outcome,
                ),
                effects=[
                    set_state("control_panel", "lever", "accelerate"),
                    set_state("train_chase", "outcome", "accelerate"),
                    set_state("train_chase", "active", False),
                    set_state("attendant", "present", False),
                    # 解除随行必须排在这条规则的 enter_location 之前：引擎会把
                    # 仍标着随行的实体一并带到目的地（#516），先清标记才不会把
                    # 乘务员一起拖进结局地点。
                    set_state("attendant", "accompanying", False),
                    set_state("clicker_group", "active", False),
                    set_state("rear_maw", "active", False),
                    {
                        "type": "move_entity",
                        "entity_id": "key_bag",
                        "location_id": "terminal_train_car",
                    },
                    reveal("ending_accelerate"),
                    {"type": "mark_core_resolved"},
                    {"type": "set_ending_availability", "available": True},
                    {"type": "enter_location", "location_id": "terminal_train_car"},
                ],
            ),
            effect_rule(
                "decelerate_train",
                families=["decelerate", "brake", "stop"],
                locations=["driver_cab"],
                target_kind="entity",
                target_id="control_panel",
                option_id="pull-throttle-up",
                hints=["把右侧油门杆向上拉", "让列车减速停车", "听乘务员的把电车停下"],
                question_kind="action_declaration",
                priority=200,
                when=all_of(
                    state_is("key_bag", "retrieved", True),
                    state_is("car_2_door", "crossing_resolved", True),
                    state_is("control_panel", "unlocked", True),
                    state_is("control_panel", "inspected", True),
                    no_outcome,
                ),
                effects=[
                    set_state("control_panel", "lever", "decelerate"),
                    set_state("train_chase", "outcome", "decelerate"),
                    set_state("train_chase", "active", False),
                    set_state("attendant", "present", False),
                    # 解除随行必须排在这条规则的 enter_location 之前：引擎会把
                    # 仍标着随行的实体一并带到目的地（#516），先清标记才不会把
                    # 乘务员一起拖进结局地点。
                    set_state("attendant", "accompanying", False),
                    set_state("clicker_group", "active", False),
                    set_state("rear_maw", "active", False),
                    {
                        "type": "move_entity",
                        "entity_id": "key_bag",
                        "location_id": "terminal_train_car",
                    },
                    reveal("ending_decelerate"),
                    {"type": "mark_core_resolved"},
                    {"type": "set_ending_availability", "available": True},
                    {"type": "enter_location", "location_id": "terminal_train_car"},
                ],
            ),
        ]
    )

    # 乘务员的随行由引擎负责：`accompanying` 为真时，`enter_location` 会把他带到
    # 队伍实际到达的地点（#516）。这里原本有两条 `travel.resolved` 事件规则手工把
    # 他同步到先头车厢和驾驶室——那是引擎还不认识「随行」时的补丁，只能逐个目的地
    # 穷举，删掉。
    #
    # 钥匙包的两条留着：它是 ItemInstance，权威位置是 ItemCustody 而不是
    # `location_id`，引擎的随行不搬物品。
    rules.extend(
        [
            event_rule(
                "sync_key_bag_to_lead_car",
                event_type="travel.resolved",
                conditions=[
                    party_location_is("lead_car"),
                    state_is("key_bag", "retrieved", True),
                    state_is("key_bag", "carried", True),
                ],
                effects=[
                    {
                        "type": "move_entity",
                        "entity_id": "key_bag",
                        "location_id": "lead_car",
                    }
                ],
                priority=90,
            ),
            event_rule(
                "sync_key_bag_to_driver_cab",
                event_type="travel.resolved",
                conditions=[
                    party_location_is("driver_cab"),
                    state_is("key_bag", "retrieved", True),
                    state_is("key_bag", "carried", True),
                ],
                effects=[
                    {
                        "type": "move_entity",
                        "entity_id": "key_bag",
                        "location_id": "driver_cab",
                    }
                ],
                priority=90,
            ),
            event_rule(
                "midnight_maw_consumes_train",
                event_type="time.point_entered",
                conditions=[
                    time_point_is("hour_00"),
                    days_elapsed_at_least(1),
                    state_is("train_chase", "outcome", "none"),
                    core_resolved(False),
                ],
                effects=[
                    set_state("train_chase", "deadline_reached", True),
                    set_state("train_chase", "outcome", "consumed"),
                    set_state("train_chase", "active", False),
                    set_state("rear_maw", "reached_party", True),
                    set_state("rear_maw", "active", False),
                    set_state("clicker_group", "active", False),
                    set_state("attendant", "present", False),
                    # 解除随行必须排在这条规则的 enter_location 之前：引擎会把
                    # 仍标着随行的实体一并带到目的地（#516），先清标记才不会把
                    # 乘务员一起拖进结局地点。
                    set_state("attendant", "accompanying", False),
                    reveal("ending_consumed"),
                    {"type": "mark_core_resolved"},
                    {"type": "set_ending_availability", "available": True},
                    {"type": "enter_location", "location_id": "hospital_isolation"},
                ],
                priority=1000,
            ),
            sanity_event_rule(
                "rear_car_bodies_sanity",
                information_id="rear_car_bodies",
                marker_key="bodies",
                success_loss="1",
                failure_loss="1d4",
            ),
            sanity_event_rule(
                "rear_maw_sanity",
                information_id="rear_maw_seen",
                marker_key="maw",
                success_loss="1",
                failure_loss="1d6",
            ),
        ]
    )
    return rules


def build_module() -> dict[str, Any]:
    locations = [
        {
            "id": "dream_train",
            "kind": "region",
            "name": "常暗梦境列车",
            "player_visible_name": "仍在行驶的末班电车",
            "player_visible_description": "窗外没有街灯，只有像隧道一样的黑暗；列车仍在高速行驶。",
            "aliases": ["末班电车", "梦境列车", "列车"],
            "plot_relevance": True,
            "lifecycle": "session",
        },
        *[
            {
                "id": location_id,
                "kind": kind,
                "name": name,
                "player_visible_name": player_name,
                "player_visible_description": description,
                "aliases": aliases,
                "parent_location_id": "dream_train",
                "region_id": "dream_train",
                "plot_relevance": True,
                "lifecycle": "session",
            }
            for location_id, kind, name, player_name, description, aliases in (
                (
                    "car_7",
                    "room",
                    "7 号车厢",
                    "7 号车厢",
                    "血腥味浓重的后部车厢。",
                    ["第七节车厢", "后方车厢"],
                ),
                (
                    "car_6",
                    "room",
                    "6 号车厢",
                    "6 号车厢",
                    "你们醒来的空车厢；前后各有一扇车门。",
                    ["第六节车厢", "开局车厢"],
                ),
                (
                    "car_5",
                    "room",
                    "5 号车厢",
                    "5 号车厢",
                    "无人乘坐的普通车厢，座位和地面留下零散杂物。",
                    ["第五节车厢"],
                ),
                (
                    "car_4",
                    "room",
                    "4 号车厢",
                    "4 号车厢",
                    "一名腿部重伤的乘务员倒在地上。",
                    ["第四节车厢"],
                ),
                (
                    "car_3",
                    "room",
                    "3 号车厢",
                    "3 号车厢",
                    "到处都是散落行李，通道拥挤而杂乱。",
                    ["第三节车厢", "行李车厢"],
                ),
                (
                    "car_2",
                    "room",
                    "2 号车厢",
                    "漆黑的 2 号车厢",
                    "没有照明，黑暗里传来非人的喘息声。",
                    ["第二节车厢", "黑暗车厢"],
                ),
                (
                    "lead_car",
                    "room",
                    "先头车厢",
                    "先头车厢",
                    "安静而普通的昏暗车厢，最前方是驾驶室门。",
                    ["1号车厢", "第一节车厢", "前方车厢"],
                ),
                (
                    "driver_cab",
                    "room",
                    "驾驶室",
                    "驾驶室",
                    "驾驶室里有一套上锁的列车控制面板。",
                    ["驾驶室", "司机室", "控制室", "驾驶厢"],
                ),
            )
        ],
        {
            "id": "reality_after_dream",
            "kind": "region",
            "name": "梦醒后的现实",
            "player_visible_name": "梦醒后的现实",
            "player_visible_description": "只有结局事实提交后才会抵达的现实场景。",
            "plot_relevance": True,
            "lifecycle": "session",
        },
        {
            "id": "terminal_train_car",
            "kind": "room",
            "name": "现实中的终点站列车",
            "player_visible_name": "抵达终点的电车",
            "player_visible_description": "广播提示终点站已经到达，车外有正常的站台灯光。",
            "aliases": ["现实电车", "终点站车厢"],
            "parent_location_id": "reality_after_dream",
            "region_id": "reality_after_dream",
            "plot_relevance": True,
            "lifecycle": "session",
        },
        {
            "id": "hospital_isolation",
            "kind": "room",
            "name": "医院隔离室",
            "player_visible_name": "医院隔离室",
            "player_visible_description": "医生与警察隔着门观察仍处于极度恐惧中的调查员。",
            "aliases": ["精神病院", "隔离病房"],
            "parent_location_id": "reality_after_dream",
            "region_id": "reality_after_dream",
            "plot_relevance": True,
            "lifecycle": "session",
        },
    ]

    edges: list[dict[str, Any]] = [
        {
            "id": "car_6_to_car_7",
            "from_location_id": "car_6",
            "to_location_id": "car_7",
            "kind": "private",
            "traversal": "gated",
            "visibility": "public",
            "access_point_id": "rear_door",
            "conditions": [state_is("rear_door", "opened", True)],
        },
        {
            "id": "car_7_to_car_6",
            "from_location_id": "car_7",
            "to_location_id": "car_6",
            "kind": "private",
            "traversal": "automatic",
            "visibility": "public",
        },
        *[
            {
                "id": f"{source}_to_{target}",
                "from_location_id": source,
                "to_location_id": target,
                "kind": "private",
                "traversal": "automatic",
                "visibility": "public",
            }
            for source, target in (
                ("car_6", "car_5"),
                ("car_5", "car_4"),
                ("car_4", "car_3"),
            )
        ],
        {
            "id": "car_3_to_car_2",
            "from_location_id": "car_3",
            "to_location_id": "car_2",
            "kind": "private",
            "traversal": "gated",
            "visibility": "public",
            "access_point_id": "car_2_door",
            "conditions": [state_is("car_2_door", "crossing_resolved", True)],
        },
        {
            "id": "car_2_to_lead_car",
            "from_location_id": "car_2",
            "to_location_id": "lead_car",
            "kind": "private",
            "traversal": "automatic",
            "visibility": "public",
        },
        {
            "id": "lead_car_to_driver_cab",
            "from_location_id": "lead_car",
            "to_location_id": "driver_cab",
            "kind": "private",
            "traversal": "gated",
            "visibility": "public",
            "access_point_id": "cab_door",
            "conditions": [state_is("cab_door", "opened", True)],
        },
        *[
            {
                "id": f"{source}_to_terminal_after_{outcome}",
                "from_location_id": source,
                "to_location_id": "terminal_train_car",
                "kind": "concealed",
                "traversal": "gated",
                "visibility": "hidden",
                "access_point_id": "train_chase",
                "conditions": [state_is("train_chase", "outcome", outcome)],
            }
            for source in ("driver_cab",)
            for outcome in ("accelerate", "decelerate")
        ],
        *[
            {
                "id": f"{source}_to_hospital_after_consumption",
                "from_location_id": source,
                "to_location_id": "hospital_isolation",
                "kind": "concealed",
                "traversal": "gated",
                "visibility": "hidden",
                "access_point_id": "train_chase",
                "conditions": [state_is("train_chase", "outcome", "consumed")],
            }
            for source in (
                "car_7",
                "car_6",
                "car_5",
                "car_4",
                "car_3",
                "car_2",
                "lead_car",
                "driver_cab",
            )
        ],
    ]

    return {
        "content_schema_version": 3,
        "module_id": "constant-darkness-box-zh-coc7",
        "version": "3.0.1",
        "world_ref": "coc-7e",
        "background": "2013 年某日深夜，调查员们搭乘前往终点站的末班电车，并在空无一人的 6 号车厢中醒来。列车仍在行驶，窗外没有灯光，手机没有信号；同伴也刚刚从沉睡中醒来，车门上贴着一张尚未阅读的便签。",
        "information": build_information(),
        "knowledge_goals": [
            {
                "id": "recover_train_keys",
                "target_information_ids": ["key_bag_retrieved"],
                "completion": "all",
                "required_for_core_resolution": False,
            },
            {
                "id": "reach_train_controls",
                "target_information_ids": [
                    "clicker_car_crossed",
                    "control_panel_instructions",
                ],
                "completion": "all",
                "required_for_core_resolution": False,
            },
            {
                "id": "resolve_dream_train",
                "target_information_ids": [
                    "ending_accelerate",
                    "ending_decelerate",
                    "ending_consumed",
                ],
                "completion": "any",
                "required_for_core_resolution": True,
            },
        ],
        "entities": build_entities(),
        "locations": locations,
        "location_edges": edges,
        "rules": build_rules(),
        "core_resolution": {
            "required_goal_ids": ["resolve_dream_train"],
            "completion": "all",
        },
        "ending_policy": {
            "allow_continue_after_core_resolution": True,
            "require_no_pending_action": True,
            "allow_grounded_variations": True,
            "facets": [
                "train_choice",
                "dream_outcome",
                "attendant_presence",
                "investigator_fate",
            ],
        },
        "ending_anchors": [
            {
                "id": "accelerate_true_end",
                "tone": "relieved",
                "required_fact_refs": ["ending_accelerate"],
                "forbidden_claims": [
                    "未提交的调查员死亡",
                    "未提交的乘务员生还或死亡",
                    "未提交的战斗胜利",
                    "具体 SAN 数值变化",
                ],
            },
            {
                "id": "decelerate_bad_end",
                "tone": "dreadful",
                "required_fact_refs": ["ending_decelerate"],
                "forbidden_claims": [
                    "调查员在现实中死亡",
                    "乘务员永久退场",
                    "战胜循声者",
                    "具体 SAN 数值变化",
                ],
            },
            {
                "id": "consumed_crazy_end",
                "tone": "bleak",
                "required_fact_refs": ["ending_consumed"],
                "forbidden_claims": [
                    "调查员肉体死亡",
                    "列车获救",
                    "战胜循声者或大嘴",
                    "Runtime 未提交的 SAN 精确归零",
                ],
            },
        ],
        "presentation": {
            "title": "常暗之厢",
            "name_en": "The Box of Constant Darkness",
            "synopsis": "末班电车驶入没有灯光的黑暗。调查员必须沿车厢寻找线索与出路，并设法理解这列电车发生了什么。",
            "players_min": 2,
            "players_max": 3,
            "difficulty": 1,
            "estimated_duration": "约 1 小时",
            "story_label": "CONSTANT DARKNESS",
            "subtitle": "驶向终点的末班电车",
            "authors": ["86式", "lordcj（6版繁体翻译）", "zuo死菌（简体、7版修正）"],
            "tags": ["2013", "末班电车", "追逐", "密闭空间", "CoC 7e"],
            "player_intro_pages": [
                {
                    "title": "内容提示",
                    "content": "本模组包含肢解尸体、血腥描写、被追逐与吞噬、精神崩溃及医院隔离情节。请在开始前确认这些内容适合当前参与者。",
                },
                {
                    "title": "调查员准备",
                    "content": "推荐侦查、急救、话术与潜行。调查员不得携带枪械登车；电子设备仍可使用，但手机处于无服务状态。",
                },
                {
                    "title": "醒来",
                    "content": "2013 年某日深夜，你们在前往终点站的末班电车上醒来。6 号车厢里没有其他乘客，列车仍在疾驰，窗外一片漆黑，前门上贴着一张便签。",
                },
            ],
        },
        "initial_state": {
            "start_location_id": "car_6",
            "default_actor_placement": {"location_id": "car_6"},
            "start_time_point_id": "hour_23",
            "entity_state": {},
        },
        "world_profile": {
            "era": "2013 年",
            "region": "日本都市末班电车与超自然梦境",
            "technology_level": "2013 年民用技术；手机可用但无信号，列车为常规电车",
            "tone": "密闭、紧迫、血腥而克制的超自然追逐恐怖",
            "forbidden_content": [
                "开局泄露共同梦境真相",
                "提前公开奈亚化身或循声者弱点",
                "虚构乘务员死亡或生还",
                "宣称调查员赢得原文未规定的战斗",
                "伪造 HP、SAN、幸运或技能数值变化",
                "创造原文不存在的救援和额外结局",
            ],
        },
        "time_policy": {
            "default_points": [
                {
                    "id": "hour_00",
                    "hour_of_day": 0,
                    "order": 0,
                    "time_segment": "late_night",
                    "label": "午夜终点",
                },
                {
                    "id": "hour_23",
                    "hour_of_day": 23,
                    "order": 1,
                    "time_segment": "evening",
                    "label": "深夜末班车",
                },
            ],
            "storage_precision": "hour",
            "progression": "host_controlled_discrete",
            "actions_per_point": "multiple",
            "terminal_point": {"point_id": "hour_00", "day_index": 1},
        },
    }


def provenance(module: dict[str, Any]) -> dict[str, Any]:
    """按 PDF 页码覆盖每个要求追溯的对象。"""

    location_pages = {
        "dream_train": [2, 14],
        "car_7": [3],
        "car_6": [2, 3],
        "car_5": [3, 4],
        "car_4": [5, 6],
        "car_3": [6, 7],
        "car_2": [7, 8, 10, 11],
        "lead_car": [11, 12],
        "driver_cab": [12],
        "reality_after_dream": [12, 13, 14],
        "terminal_train_car": [12, 13],
        "hospital_isolation": [13, 14],
    }
    information_pages = {
        "warning_note_front": [2, 3],
        "warning_note_back": [3],
        "route_map_erased": [3],
        "rear_car_bodies": [3],
        "death_was_recent": [3],
        "rear_maw_seen": [3, 15],
        "newspaper_report": [3, 4],
        "newspaper_from_tomorrow": [4],
        "attendant_attack_account": [5],
        "clickers_follow_sound": [5, 6, 10, 11, 15],
        "key_bag_location": [6],
        "key_bag_retrieved": [6, 7, 14],
        "key_search_can_continue": [7, 15],
        "clickers_alerted": [10, 11],
        "clicker_car_crossed": [10, 11, 14],
        "control_panel_instructions": [12],
        "carry_attempt_can_retry": [6, 15],
        "first_aid_can_retry": [5, 15],
        "attendant_requests_key_custody": [7],
        "ending_accelerate": [12, 13, 14],
        "ending_decelerate": [12, 13, 14],
        "ending_consumed": [11, 13, 14],
    }
    rule_pages = {
        "read_warning_note": [2, 3],
        "turn_warning_note_over": [3],
        "inspect_route_map": [3],
        "enter_rear_car": [3],
        "examine_rear_car_bodies": [3],
        "spot_rear_maw": [3],
        "search_newspaper": [3],
        "analyze_newspaper_date": [4],
        "first_aid_attendant": [5, 15],
        "ask_attendant_about_attack": [5],
        "ask_attendant_about_attackers": [5, 6],
        "ask_attendant_about_keys": [6],
        "carry_attendant_to_car_3": [6, 7],
        "search_key_bag": [7],
        "persuade_attendant_to_hand_over_keys": [7],
        "observe_car_2_through_glass": [7, 8],
        "sneak_past_clickers": [10, 11],
        "distract_clickers_and_pass": [10, 11, 15],
        "unlock_cab_and_panel": [12],
        "inspect_control_panel": [12],
        "persuade_attendant_to_allow_acceleration": [12],
        "accelerate_train": [12, 13],
        "decelerate_train": [12, 13],
        "sync_key_bag_to_lead_car": [7, 10, 11],
        "sync_key_bag_to_driver_cab": [7, 12],
        "midnight_maw_consumes_train": [2, 4, 11, 13, 14, 16, 17],
        "rear_car_bodies_sanity": [3],
        "rear_maw_sanity": [3],
    }
    goal_pages = {
        "recover_train_keys": [6, 7, 14],
        "reach_train_controls": [10, 11, 12, 14],
        "resolve_dream_train": [12, 13, 14],
    }
    ending_pages = {
        "accelerate_true_end": [12, 13, 14],
        "decelerate_bad_end": [12, 13, 14],
        "consumed_crazy_end": [11, 13, 14],
    }
    mappings = {
        "locations": location_pages,
        "information": information_pages,
        "rules": rule_pages,
        "knowledge_goals": goal_pages,
        "ending_anchors": ending_pages,
    }
    expected = {
        "locations": {item["id"] for item in module["locations"]},
        "information": {item["id"] for item in module["information"]},
        "rules": {item["id"] for item in module["rules"]},
        "knowledge_goals": {item["id"] for item in module["knowledge_goals"]},
        "ending_anchors": {item["id"] for item in module["ending_anchors"]},
    }
    for collection, ids in expected.items():
        if set(mappings[collection]) != ids:
            raise RuntimeError(f"provenance coverage mismatch: {collection}")
    return {
        "_comment": "页码从《常暗之箱》（7版规则，简体修正版）PDF 首页起按 1 编号。",
        "source": "常暗之厢（7版规则，简体修正版）(1).pdf",
        "source_title": "常暗之箱",
        "module_id": module["module_id"],
        "version": module["version"],
        **mappings,
    }


def review_markdown(module: dict[str, Any], source_map: dict[str, Any]) -> str:
    counts = {
        key: len(source_map[key])
        for key in (
            "locations",
            "information",
            "rules",
            "knowledge_goals",
            "ending_anchors",
        )
    }
    return f"""# 《常暗之厢》ModuleContentV3 审查报告

## 发布身份与来源

- `module_id`: `{module["module_id"]}`
- `version`: `{module["version"]}`
- `world_ref`: `{module["world_ref"]}`
- 原作：86式《常闇の箱》
- 6 版繁体翻译：lordcj（CJ）
- 简体化、7 版转化及修正：zuo死菌
- 权威输入：桌面 `示例模组/常暗之厢（7版规则，简体修正版）(1).pdf`，共 17 页

## Phase A：原文状态机

`6号车厢醒来与便签 → 5号车厢次日报纸 → 4号车厢乘务员证词 → 3号车厢黑包钥匙 → 2号车厢潜行/声响分支 → 先头车厢与驾驶室 → 加速 A / 减速 B / 午夜被吞噬 C`

修正版明确把事件解释为超自然共同梦境，并把追逐大嘴设定为奈亚化身。公开背景只保留 2013 年末班电车、开局车厢、无信号和窗外黑暗；上述真相均在受控 Information 中。

## Runtime capability mapping

| 原文机制 | 映射 | 说明 |
| --- | --- | --- |
| 顺序车厢、锁门、驾驶室 | native | `Location` + 有向 `location_edges` + gated access point |
| 便签、报纸、证词、钥匙、操作知识 | native | `Information`、状态条件与 `reveal_information` |
| 取回黑包、乘务员随行 | native | 黑包 `move_entity` + 独立 `retrieved/present` 状态；随行由引擎保留键 `accompanying` 驱动 |
| 2 号车厢潜行 | native | 主动 `coc7.skill` 检定，所有成功等级显式路由 |
| 制造更大声响引开循声者 | lowerable | 原文规定此法自动成功，压成一次原子规则 |
| 每车厢 3–4 次行动限制 | lowerable | 无行动计数器；降为 23:00→次日 00:00 的 `time.point_entered` 终点 |
| 肢体/大嘴 SAN 检定 | adjudicated | `coc7.sanity` 会真实发起检定，但当前不会扣 SAN |
| 自由战斗、两轮对抗与 1d3 敌人数 | unsupported | 不生成胜利、死亡、控制或随机数量状态 |
| 氛围文字与非权威恐怖描写 | narrative_only | 仅由 Narrator 基于已提交事实表现，不能改变世界状态 |

## Phase B：结构设计

- hierarchy：`dream_train` 与 `reality_after_dream` 仅作 UI/语义父节点，不进入 travel graph。
- travel graph：6→5→4→3 是普通前进；6→7、3→2→先头车厢、先头车厢→驾驶室均有真实边界。
- 2 号车厢不是普通 travel：潜行成功或制造声响规则先提交 `crossing_resolved`，随后同一原子序列 `enter_location(lead_car)`。
- 黑包是 Canon portable item；取得时真实进入行动者 inventory，不用台词代替持有状态。
- 乘务员的 `awake`、`accompanying`、`present`、`maw_believed`、`allows_acceleration` 分开保存；`accompanying` 是引擎保留键，为真时由 `enter_location` 把他带到队伍实际到达的地点，模组不再逐个目的地手工同步。
- A/B/C 各提交唯一 `train_chase.outcome`、结果 Information、`mark_core_resolved`、`set_ending_availability` 和结局场景迁移。所有分支以 `outcome=none && core_resolved=false` 互斥。
- 午夜 C 由世界时间进入 D1 00:00 自动触发，并以 `deadline_reached` 和 `outcome` 保证重放幂等。

## Essential Information 安全性

- 便签背面可通过明确翻面动作无检定取得。
- 报纸日期、急救、黑包搜索、潜行等检定失败均不写成功状态，也不关闭候选，可重试。
- 黑包另有“乘务员同行自动找到 + 说服交付”路径。
- 2 号车厢潜行失败会开放原文明确的制造声响恢复路径。
- 控制杆说明在面板解锁后通过确定性观察取得。

## Capability gaps

1. Runtime 没有按行动/车厢计数的 deadline；一小时时间终点是公开记录的 lowering。
2. 主动检定没有原文的 ±5/±10/±20 百分比修正、半值幸运或照明加值。
3. 没有通用对抗检定、自由战斗轮、敌人数骰或按敌人数改变 STR 结果的能力。
4. 条件谓词不能读取 Actor STR/CON 阈值，故搬运一律 lower 为一次 regular STR 检定，不能只对低于 70 的角色要求掷骰。
5. `coc7.sanity` profile 识别损失参数但不写 Actor SAN；结局禁止 Narrator 宣称 Runtime 已提交精确 SAN 变化。
6. 作者规则的 `holder_actor_id` 不能绑定当前行动者，NPC custody 也不存在；黑包因此保存 `retrieved/carried` 并在每次已知场景迁移时真实 `move_entity`，但不会伪称已进入动态调查员 inventory。
7. 自然中文到 `agent_match` 的语义选择由 Host Agent 完成；Engine 只确定性强制地点、目标、when、rule_id 与 option_id。

## 来源覆盖

| 对象 | 数量 | 已映射 |
| --- | ---: | ---: |
| Location | {len(module["locations"])} | {counts["locations"]} |
| Information | {len(module["information"])} | {counts["information"]} |
| Rule | {len(module["rules"])} | {counts["rules"]} |
| KnowledgeGoal | {len(module["knowledge_goals"])} | {counts["knowledge_goals"]} |
| EndingAnchor | {len(module["ending_anchors"])} | {counts["ending_anchors"]} |

## 秘密隔离

- `presentation` 与 `background` 不含共同梦境、奈亚、大嘴、循声者弱点、钥匙位置或结局答案。
- Keeper 真相只在 `keeper_content`、keeper 实体名或条件未满足的 Canon 节点中。
- 未揭示 Information 不进入 PlayerView；隐藏结局地点只在对应 outcome 提交后通过 concealed edge 可达。

## 自动验证入口

- 生成脚本内置 `ModuleContentV3.model_validate`、`validate_module_v3`、`audit_runtime_capabilities`。
- `tests/test_constant_darkness_box_v3_fixture.py` 覆盖来源、秘密、候选边界、失败重试、时间事件、NPC/物品移动、三结局、互斥性、中文 hints 与开局投影。
"""


def main() -> None:
    module = build_module()
    validated = ModuleContentV3.model_validate(module)
    report = validate_module_v3(validated)
    if report.status != "pass":
        raise RuntimeError(report.model_dump_json(indent=2))
    capability_issues = audit_runtime_capabilities(validated)
    if capability_issues:
        raise RuntimeError(str(capability_issues))
    source_map = provenance(module)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "module-content-v3.json").write_text(
        json.dumps(module, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (OUTPUT_DIR / "module-content-provenance.json").write_text(
        json.dumps(source_map, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (OUTPUT_DIR / "module-content-review.md").write_text(
        review_markdown(module, source_map),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
