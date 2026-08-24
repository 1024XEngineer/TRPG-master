"""生成《幸福蛙蛙村》的稳定 ModuleContentV3 与人工审查产物。

原文包含自由战斗、逐角色四阶段异变和任意 KP 能力。当前生产运行时不能安全
拥有这些自由格式状态，因此本脚本保留调查、时间、揭密与抉择主线，并把三个
可回放结果收敛为说服信使、破坏水晶和主动离开。不得在这里用 Narrator 文本
冒充 HP、SAN、角色死亡、永久退役或个体变异的权威提交。
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
    ROOT / "docs" / "module-parser" / "examples" / "module-content-validation" / "幸福蛙蛙村"
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
    """构造 Keeper 与玩家文本严格分离的信息节点。"""

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
    """只使用运行时已经注册的实体状态谓词。"""

    return {
        "op": "predicate",
        "predicate": "entity_state_is",
        "args": {"entity_id": entity_id, "key": key, "value": value},
    }


def time_of_day_is(value: str) -> dict[str, Any]:
    """构造引擎已注册的昼夜阶段谓词。"""

    return {
        "op": "predicate",
        "predicate": "time_of_day_is",
        "args": {"value": value},
    }


def info_is(item_id: str) -> dict[str, Any]:
    """构造已揭示信息谓词。"""

    return {
        "op": "predicate",
        "predicate": "information_is",
        "args": {"id": item_id},
    }


def entity(
    entity_id: str,
    name: str,
    description: str,
    *,
    location: str,
    kind: str = "object",
    state: dict[str, Any] | None = None,
    visible_when: list[dict[str, Any]] | None = None,
    portable: bool = False,
    visibility: str = "public",
) -> dict[str, Any]:
    """构造不会在运行时任意生成的 Canon Entity。"""

    payload: dict[str, Any] = {
        "id": entity_id,
        "kind": kind,
        "name": name,
        "player_visible_name": name,
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
        payload["item_component"] = {
            "portable": True,
            "unique": True,
            "quantity": 1,
        }
    return payload


def agent_trigger(
    families: list[str],
    locations: list[str],
    target_kind: str,
    target_id: str,
    option_id: str,
    hints: list[str],
    when: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """每条玩家行动规则都带明确地点、目标和语义范围。"""

    trigger = {
        "kind": "agent_match",
        "scope": {
            "action_families": families,
            "location_ids": locations,
            "target_kinds": [target_kind],
            "target_ids": [target_id],
        },
        "question": {"kind": "method", "semantic_hints": hints},
        "options": [{"id": option_id, "semantic_hints": hints}],
    }
    if when is not None:
        trigger["when"] = when
    return trigger


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
) -> dict[str, Any]:
    """构造只提交封闭 ActionEffect 的确定性规则。"""

    steps: list[dict[str, Any]] = []
    for index, effect in enumerate(effects):
        next_id = f"effect_{index + 1}" if index + 1 < len(effects) else "finish"
        steps.append(
            {
                "id": f"effect_{index}",
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
            locations,
            target_kind,
            target_id,
            option_id,
            hints,
        ),
        "execution": {
            "branches": [{"id": option_id, "entry_step_id": "effect_0"}],
            "steps": steps,
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
    skill_id: str,
    success_effects: list[dict[str, Any]],
    failure_effects: list[dict[str, Any]],
    difficulty: str = "regular",
    when: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """构造失败仍可重试或获得替代提示的正式 COC7 检定。"""

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
                "allow_luck": True,
                "allow_push": True,
            },
            "result_routes": SUCCESS_ROUTES,
        }
    ]
    for prefix, effects in (
        ("success", success_effects),
        ("failure", failure_effects),
    ):
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
            locations,
            target_kind,
            target_id,
            option_id,
            [skill_id, *families, *[target_id]],
            when,
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
    effects: list[dict[str, Any]],
) -> dict[str, Any]:
    """构造只监听生产运行时实际派发事件的规则。"""

    steps: list[dict[str, Any]] = []
    for index, effect in enumerate(effects):
        next_id = f"effect_{index + 1}" if index + 1 < len(effects) else "finish"
        steps.append(
            {
                "id": f"effect_{index}",
                "kind": "effect",
                "effect": effect,
                "next_step_id": next_id,
            }
        )
    steps.append({"id": "finish", "kind": "finish"})
    when = conditions[0] if len(conditions) == 1 else {"op": "all", "items": conditions}
    return {
        "id": rule_id,
        "trigger": {
            "kind": "event",
            "event_type": event_type,
            "when": when,
            "entry_branch_id": "default",
        },
        "execution": {
            "branches": [{"id": "default", "entry_step_id": "effect_0"}],
            "steps": steps,
        },
    }


def reveal(item_id: str) -> dict[str, Any]:
    return {"type": "reveal_information", "information_id": item_id, "scope": "party"}


def set_state(entity_id: str, key: str, value: Any) -> dict[str, Any]:
    return {
        "type": "change_entity_state",
        "entity_id": entity_id,
        "key": key,
        "value": value,
    }


def build_information() -> list[dict[str, Any]]:
    """把原文的调查事实分离为可揭示 Canon Information。"""

    return [
        information(
            "commission_received",
            "寻找詹姆斯的委托",
            "莱恩夫妇委托调查员寻找失踪一周的儿子詹姆斯。",
            "莱恩夫妇请你们寻找失踪一周的詹姆斯，并提供了照片和预付金。",
            criticality="essential",
        ),
        information(
            "frog_resort_flyer",
            "蛙蛙度假村传单",
            "所有导入最终都把调查员引向同一张传单和城郊老林地。",
            "传单邀请生活陷入低谷的人免费前往城郊的蛙蛙度假村寻找幸福。",
            criticality="essential",
        ),
        information(
            "flyer_is_hand_drawn",
            "手绘传单",
            "传单看似印刷，实际是逐字手绘，并带有青蛙般的气味。",
            "细看后，你发现传单并非印刷品，而是精确得异乎寻常的手绘作品。",
        ),
        information(
            "missing_people_pattern",
            "重复发生的失踪",
            "过去三至六个月至少七名处于人生低谷者在前往不存在的度假区后失踪。",
            "近期多起失踪案都有相同模式：当事人处于低谷，声称要去安静地方，随后消失。",
            criticality="essential",
        ),
        information(
            "villagers_shared_dreams",
            "村民们的共同梦境",
            "周边村民梦到逝者或白色少女询问是否幸福，梦后有人走入树林失踪。",
            "不同村民做过相似的美梦：白色少女不断询问“你幸福吗”，随后有人走入树林。",
        ),
        information(
            "resort_has_no_registration",
            "官方记录中的空白",
            "旅游、规划、电话系统均无蛙蛙度假村记录。",
            "官方机构一致否认度假村存在，地址所在区域也不允许商业开发。",
        ),
        information(
            "ezra_warning",
            "埃兹拉的警告",
            "幸存者埃兹拉确认白发少女、美梦、身体异变和池塘青蛙都属于陷阱。",
            "路边的幸存者警告你们：幸福是陷阱，梦会吞噬人，池塘里的青蛙也不正常。",
            criticality="essential",
        ),
        information(
            "staff_are_conditioned",
            "整齐得过分的员工",
            "员工被信使同化，笑容与语调缺乏个人情感。",
            "度假村员工的笑容和语调像经过统一训练，热情中缺少真实情绪。",
        ),
        information(
            "messenger_happiness_logic",
            "信使对幸福的理解",
            "信使真诚地认为消除选择、让人永眠就是幸福。",
            "信使并非假装善意，但她把“永远不用面对痛苦”当成唯一正确的幸福。",
            criticality="essential",
        ),
        information(
            "james_refuses_home",
            "詹姆斯拒绝回家",
            "詹姆斯已深度依赖美梦并把度假村视作家。",
            "詹姆斯拒绝离开，坚称这里才是他的家，并劝你们也留下。",
            criticality="essential",
        ),
        information(
            "james_resists_forced_removal",
            "詹姆斯抗拒强行带离",
            "在信使影响解除前强行控制詹姆斯，会使他歇斯底里地挣扎呼救，并惊动员工与幸福信使。",
            "詹姆斯剧烈挣扎并向信使呼救；继续强行带他离开只会加重他的痛苦。",
            criticality="essential",
        ),
        information(
            "james_forced_removal_tragedy",
            "强行带离的悲剧",
            "未解除信使影响便强行把詹姆斯带出度假村，会引发严重戒断和精神崩溃；"
            "他最终会在返程途中自尽，安眠或击晕不能规避这一来源结局。",
            "远离度假村后，詹姆斯出现严重戒断与精神崩溃，最终在返程途中结束了"
            "自己的生命。强行带离没能救回他。",
            criticality="essential",
        ),
        information(
            "happiness_booklet_doctrine",
            "《来一起拥抱幸福吧！》",
            "手册用放下自我、融入自然与无忧梦境包装同化理念。",
            "客房手册反复写着“放下自我、融入自然”和“幸福即在无忧的梦中”。",
        ),
        information(
            "guests_show_mutation",
            "游客的青蛙特征",
            "部分游客已出现湿冷皮肤、蹼膜或青蛙头等异变。",
            "仔细观察后，你发现部分游客身上已经出现不属于人类的青蛙特征。",
            criticality="essential",
        ),
        information(
            "all_liquids_use_pond_water",
            "餐饮中的幸福之水",
            "汤、饮料和供水都来自蛙鸣泉，饮用会产生幻觉并加速异变。",
            "厨房用带着微光的池水烹调汤和饮料，员工称它为“幸福之水”。",
            criticality="essential",
        ),
        information(
            "water_causes_hallucinations",
            "外来的幸福感",
            "池水会针对内心渴望制造幻觉；首版不伪造逐角色变异状态。",
            "接触这里的水会带来不属于自己的舒适感和私人幻觉，清醒后仍令人不安。",
        ),
        information(
            "frogs_were_people",
            "梦游青蛙的真相",
            "青蛙跨物种和平共处、发出人声，实为被转化并沉浸美梦的受害者。",
            "蛙鸣中夹杂着人类话语；这些呆滞的青蛙很可能曾经是人。",
            criticality="essential",
        ),
        information(
            "staff_notes_confessions",
            "员工留下的纸条",
            "纸条显示萨曼莎想传播幸福，詹姆斯爱慕并依赖信使。",
            "员工纸条表明，他们并非普通雇员，而是在主动帮助信使传播“幸福”。",
        ),
        information(
            "messenger_origin_notes",
            "信使笔记中的来历",
            "信使来自异界，为降低维持美梦的消耗而把沉睡者变成青蛙。",
            "笔记说明信使来自遥远世界；访客过多后，她把做梦的人变成青蛙以节省力量。",
            criticality="essential",
        ),
        information(
            "night_has_fallen",
            "第一夜来临",
            "夜晚会出现低语，信使前往池塘为水晶补充能量。",
            "夜色降临，温柔的声音在耳边询问：“对你而言，什么是幸福？”",
        ),
        information(
            "night_ritual_seen",
            "池塘边的夜间仪式",
            "信使从池底取出水晶并注入能量，青蛙如朝圣般面向她。",
            "你看到信使从池底取出透明水晶注入微光，青蛙全部朝她伏下。",
            criticality="essential",
        ),
        information(
            "crystal_is_power_core",
            "梦境水晶的作用",
            "透明水晶借水等媒介传播美梦，也是度假村力量的可破坏核心。",
            "水晶通过池水传播美梦；离开媒介或被破坏，度假村的力量就会失去核心。",
            criticality="essential",
        ),
        information(
            "crystal_retrieved",
            "水晶被带到岸边",
            "困难潜水成功后，调查员把既有 Canon 水晶带到岸边。",
            "你把透明水晶从池底带到了岸边。",
            criticality="essential",
        ),
        information(
            "debate_failed_hint",
            "信使仍未动摇",
            "说服失败不会锁死，玩家可补充选择权、痛苦与爱的证据后重试。",
            "信使仍不理解。也许需要用已经发现的受害者、选择权和真实关系反驳她。",
        ),
        information(
            "messenger_convinced",
            "信使承认错误",
            "调查员以证据和论证动摇信使，她主动终止美梦。",
            "信使终于理解：被剥夺选择的幸福并不是真正的幸福。她决定释放所有人。",
            criticality="essential",
        ),
        information(
            "crystal_destroyed",
            "梦境核心被破坏",
            "水晶被破坏，度假村的转化力量消散。",
            "水晶碎裂后，覆盖度假村的微光与雾气开始消散。",
            criticality="essential",
        ),
        information(
            "victims_released",
            "受害者恢复人形",
            "信使放弃计划或水晶被破坏后，青蛙受害者与员工恢复。",
            "池塘里的青蛙和被同化的员工逐渐恢复为人类。",
            criticality="essential",
        ),
        information(
            "james_returns_home",
            "詹姆斯获救",
            "解除力量后，詹姆斯清醒并能随调查员回到莱恩家。",
            "詹姆斯从美梦中清醒，愿意和你们离开度假村。",
            criticality="essential",
        ),
        information(
            "escaped_unresolved",
            "主动离开度假村",
            "调查员可以随时离开；未破坏核心时度假村仍可能在别处出现。",
            "你们离开了度假村，但它的真相和失踪者仍留在雾中。未来或许还会有人收到传单。",
            criticality="essential",
        ),
        information(
            "accepted_happiness",
            "选择留下",
            "只有玩家明确接受信使理念时才能开放留下结局，不自动永久退役角色。",
            "你明确选择留在这里，接受信使所说的“幸福”。最终后果仍需在结局确认时决定。",
            criticality="essential",
        ),
    ]


def build_entities() -> list[dict[str, Any]]:
    """声明稳定目标；最终互动节点由事实或状态控制可见性。"""

    return [
        entity(
            "lane_commission",
            "莱恩夫妇的委托",
            "寻找詹姆斯的正式委托。",
            location="lane_manor",
        ),
        entity(
            "resort_flyer",
            "蛙蛙度假村传单",
            "设计精美、地址模糊的彩色传单。",
            location="lane_manor",
            portable=True,
        ),
        entity(
            "missing_files",
            "近期失踪档案",
            "警局近期失踪人口报告。",
            location="pretrip_investigation",
        ),
        entity(
            "villager_accounts",
            "周边村民",
            "对林地与共同梦境讳莫如深的居民。",
            location="pretrip_investigation",
            kind="npc",
        ),
        entity(
            "ezra",
            "埃兹拉",
            "从度假村逃出的推销员，手指间仍有淡绿色蹼膜。",
            location="forest_road",
            kind="npc",
        ),
        entity(
            "messenger",
            "幸福信使",
            "白发、绿色斗篷、真诚地宣称要带来幸福的少女。",
            location="resort_reception",
            kind="npc",
            state={"convinced": False},
        ),
        entity(
            "emily",
            "艾米丽",
            "笑容完美无瑕的接待女仆。",
            location="resort_reception",
            kind="npc",
        ),
        entity(
            "james",
            "詹姆斯·莱恩",
            "调查员寻找的失踪青年。",
            location="resort_reception",
            kind="npc",
            state={"released": False, "forced_removal": False, "alive": True},
        ),
        entity(
            "staff_door",
            "员工区入口",
            "不向游客开放的员工通道。",
            location="resort_reception",
            state={"open": False},
        ),
        entity(
            "happiness_booklet",
            "《来一起拥抱幸福吧！》",
            "客房床头的宣传手册。",
            location="guest_room",
        ),
        entity(
            "frog_head_guest",
            "宽衣游客",
            "用宽大衣物遮挡身体异样的游客。",
            location="guest_room",
            kind="npc",
        ),
        entity(
            "contaminated_water",
            "汤品与饮料",
            "由蛙鸣泉池水制作的饮品与汤。",
            location="dining_kitchen",
        ),
        entity(
            "kitchen_barrel",
            "厨房水桶",
            "装着带微弱磷光池水的大桶。",
            location="dining_kitchen",
        ),
        entity(
            "frog_pond",
            "蛙鸣泉",
            "度假村中心、遍布异常青蛙的池塘。",
            location="frog_pond",
        ),
        entity(
            "dream_frogs",
            "梦游青蛙",
            "几乎不躲避来人的鲜艳青蛙。",
            location="frog_pond",
            kind="npc",
        ),
        entity(
            "night_ritual",
            "池塘边的微光",
            "夜间池塘出现的规律微光与朝圣般蛙群。",
            location="frog_pond",
            state={"active": False},
            visible_when=[state_is("night_ritual", "active", True)],
        ),
        entity(
            "dream_crystal",
            "梦境水晶",
            "信使从池底取出的透明水晶。",
            location="frog_pond",
            state={"known": False, "retrieved": False, "destroyed": False},
            visible_when=[state_is("dream_crystal", "known", True)],
        ),
        entity(
            "staff_notes",
            "员工纸条",
            "未完成传单间夹着的零散纸条。",
            location="staff_area",
        ),
        entity(
            "messenger_notes",
            "信使的私人笔记",
            "记录她的来历、目标和转化原因。",
            location="messenger_bedroom",
        ),
        entity(
            "nutrient_barrels",
            "营养液桶",
            "散发甜腻气味的营养液。",
            location="storage_room",
        ),
        entity(
            "final_debate",
            "关于幸福的最终辩论",
            "只有掌握信使逻辑和受害者证据后才有意义的对话。",
            location="resort_reception",
            state={"available": False},
            visible_when=[state_is("final_debate", "available", True)],
        ),
        entity(
            "resort_exit",
            "返程道路",
            "穿过雾气离开度假村的道路。",
            location="resort_boundary",
            state={"open": True},
        ),
        entity(
            "resort_state",
            "度假村力量",
            "只保存共享、可审计的结局状态，不替代逐角色异变。",
            location="resort_reception",
            state={"victims_released": False, "core_broken": False},
            visibility="keeper",
        ),
    ]


def build_rules() -> list[dict[str, Any]]:
    """构建可由真实引擎逐步提交的调查与三结局主线。"""

    rules: list[dict[str, Any]] = [
        effect_rule(
            "accept_lane_commission",
            families=["accept", "investigate", "talk"],
            locations=["lane_manor"],
            target_kind="entity",
            target_id="lane_commission",
            option_id="take-case",
            hints=["接受寻人委托", "寻找詹姆斯"],
            effects=[reveal("commission_received"), reveal("frog_resort_flyer")],
        ),
        check_rule(
            "inspect_resort_flyer",
            families=["inspect", "research"],
            locations=["lane_manor"],
            target_kind="entity",
            target_id="resort_flyer",
            option_id="library-use",
            skill_id="library-use",
            success_effects=[reveal("flyer_is_hand_drawn")],
            failure_effects=[reveal("frog_resort_flyer")],
        ),
        check_rule(
            "research_missing_people",
            families=["research", "search"],
            locations=["pretrip_investigation"],
            target_kind="entity",
            target_id="missing_files",
            option_id="library-use",
            skill_id="library-use",
            success_effects=[
                reveal("missing_people_pattern"),
                reveal("resort_has_no_registration"),
            ],
            failure_effects=[reveal("missing_people_pattern")],
        ),
        check_rule(
            "ask_villagers_about_dreams",
            families=["ask", "persuade", "talk"],
            locations=["pretrip_investigation"],
            target_kind="entity",
            target_id="villager_accounts",
            option_id="persuade",
            skill_id="persuade",
            success_effects=[reveal("villagers_shared_dreams")],
            failure_effects=[reveal("resort_has_no_registration")],
        ),
        check_rule(
            "calm_ezra",
            families=["calm", "talk", "analyze"],
            locations=["forest_road"],
            target_kind="entity",
            target_id="ezra",
            option_id="psychoanalysis",
            skill_id="psychoanalysis",
            success_effects=[reveal("ezra_warning")],
            failure_effects=[reveal("ezra_warning")],
        ),
        check_rule(
            "read_messenger_intent",
            families=["observe", "analyze", "talk"],
            locations=["resort_reception"],
            target_kind="entity",
            target_id="messenger",
            option_id="psychology",
            skill_id="psychology",
            success_effects=[reveal("messenger_happiness_logic")],
            failure_effects=[reveal("staff_are_conditioned")],
        ),
        effect_rule(
            "talk_to_james",
            families=["ask", "talk", "rescue"],
            locations=["resort_reception"],
            target_kind="entity",
            target_id="james",
            option_id="ask-to-return",
            hints=["询问詹姆斯", "请他回家"],
            effects=[reveal("james_refuses_home")],
        ),
        effect_rule(
            "force_james_against_his_will",
            families=["attack", "force", "restrain", "carry", "rescue"],
            locations=["resort_reception", "resort_boundary"],
            target_kind="entity",
            target_id="james",
            option_id="force-james",
            hints=[
                "强行把詹姆斯带走",
                "击晕詹姆斯",
                "用安眠药控制詹姆斯",
                "违背詹姆斯意愿拖走他",
            ],
            effects=[
                set_state("james", "forced_removal", True),
                reveal("james_resists_forced_removal"),
            ],
        ),
        effect_rule(
            "force_james_out_of_resort",
            families=["escape", "leave", "travel", "carry", "rescue"],
            locations=["resort_reception", "resort_boundary"],
            target_kind="location",
            target_id="outside",
            option_id="force-james-outside",
            hints=[
                "击晕詹姆斯后强行带离度假村",
                "强行把詹姆斯拖出度假村",
                "用安眠药控制詹姆斯后带离",
                "违背詹姆斯意愿把他带回家",
            ],
            effects=[
                {"type": "enter_location", "location_id": "outside"},
                set_state("james", "forced_removal", True),
                set_state("james", "alive", False),
                reveal("james_forced_removal_tragedy"),
                {"type": "mark_core_resolved"},
                {"type": "set_ending_availability", "available": True},
            ],
        ),
        effect_rule(
            "read_happiness_booklet",
            families=["read", "inspect"],
            locations=["guest_room"],
            target_kind="entity",
            target_id="happiness_booklet",
            option_id="read-booklet",
            hints=["阅读客房手册", "理解幸福宣传"],
            effects=[reveal("happiness_booklet_doctrine")],
        ),
        check_rule(
            "inspect_mutating_guest",
            families=["inspect", "observe"],
            locations=["guest_room"],
            target_kind="entity",
            target_id="frog_head_guest",
            option_id="spot-hidden",
            skill_id="spot-hidden",
            success_effects=[reveal("guests_show_mutation")],
            failure_effects=[reveal("staff_are_conditioned")],
        ),
        check_rule(
            "trace_kitchen_water",
            families=["inspect", "trace", "ask"],
            locations=["dining_kitchen"],
            target_kind="entity",
            target_id="kitchen_barrel",
            option_id="spot-hidden",
            skill_id="spot-hidden",
            success_effects=[reveal("all_liquids_use_pond_water")],
            failure_effects=[reveal("all_liquids_use_pond_water")],
        ),
        check_rule(
            "resist_happiness_water",
            families=["drink", "taste"],
            locations=["dining_kitchen"],
            target_kind="entity",
            target_id="contaminated_water",
            option_id="POW",
            skill_id="POW",
            success_effects=[reveal("water_causes_hallucinations")],
            failure_effects=[reveal("water_causes_hallucinations")],
        ),
        check_rule(
            "study_dream_frogs",
            families=["study", "inspect", "listen"],
            locations=["frog_pond"],
            target_kind="entity",
            target_id="dream_frogs",
            option_id="natural-world",
            skill_id="natural-world",
            success_effects=[reveal("frogs_were_people")],
            failure_effects=[reveal("guests_show_mutation")],
        ),
        check_rule(
            "infiltrate_staff_area",
            families=["sneak", "enter", "distract"],
            locations=["resort_reception"],
            target_kind="entity",
            target_id="staff_door",
            option_id="stealth",
            skill_id="stealth",
            success_effects=[
                set_state("staff_door", "open", True),
                {"type": "enter_location", "location_id": "staff_area"},
            ],
            failure_effects=[reveal("staff_are_conditioned")],
        ),
        effect_rule(
            "read_staff_notes",
            families=["read", "search"],
            locations=["staff_area"],
            target_kind="entity",
            target_id="staff_notes",
            option_id="read-notes",
            hints=["阅读员工纸条", "调查未完成传单"],
            effects=[reveal("staff_notes_confessions"), reveal("james_refuses_home")],
        ),
        check_rule(
            "read_messenger_notes",
            families=["read", "research"],
            locations=["messenger_bedroom"],
            target_kind="entity",
            target_id="messenger_notes",
            option_id="library-use",
            skill_id="library-use",
            success_effects=[
                reveal("messenger_origin_notes"),
                reveal("messenger_happiness_logic"),
                reveal("frogs_were_people"),
                reveal("crystal_is_power_core"),
                set_state("dream_crystal", "known", True),
            ],
            failure_effects=[
                reveal("messenger_origin_notes"),
                reveal("messenger_happiness_logic"),
            ],
        ),
        check_rule(
            "observe_night_ritual",
            families=["observe", "follow", "hide"],
            locations=["frog_pond"],
            target_kind="entity",
            target_id="night_ritual",
            option_id="spot-hidden",
            skill_id="spot-hidden",
            success_effects=[
                reveal("night_ritual_seen"),
                reveal("crystal_is_power_core"),
                set_state("dream_crystal", "known", True),
            ],
            failure_effects=[reveal("night_has_fallen")],
        ),
        check_rule(
            "retrieve_dream_crystal",
            families=["dive", "retrieve", "swim"],
            locations=["frog_pond"],
            target_kind="entity",
            target_id="dream_crystal",
            option_id="swim",
            skill_id="swim",
            difficulty="hard",
            success_effects=[
                set_state("dream_crystal", "retrieved", True),
                reveal("crystal_retrieved"),
            ],
            failure_effects=[reveal("crystal_is_power_core")],
        ),
        check_rule(
            "persuade_happiness_messenger",
            families=["persuade", "debate", "appeal"],
            locations=["resort_reception"],
            target_kind="entity",
            target_id="final_debate",
            option_id="persuade-with-evidence",
            skill_id="persuade",
            difficulty="hard",
            when=state_is("final_debate", "available", True),
            success_effects=[
                set_state("messenger", "convinced", True),
                set_state("resort_state", "victims_released", True),
                set_state("james", "released", True),
                reveal("messenger_convinced"),
                reveal("victims_released"),
                reveal("james_returns_home"),
                {"type": "mark_core_resolved"},
                {"type": "set_ending_availability", "available": True},
            ],
            failure_effects=[reveal("debate_failed_hint")],
        ),
        effect_rule(
            "destroy_dream_crystal",
            families=["destroy", "break"],
            locations=["crystal_shore"],
            target_kind="entity",
            target_id="dream_crystal",
            option_id="break-crystal",
            hints=["破坏已经带上岸的水晶", "终止美梦核心"],
            effects=[
                set_state("dream_crystal", "destroyed", True),
                set_state("resort_state", "core_broken", True),
                set_state("resort_state", "victims_released", True),
                set_state("james", "released", True),
                reveal("crystal_destroyed"),
                reveal("victims_released"),
                reveal("james_returns_home"),
                {"type": "mark_core_resolved"},
                {"type": "set_ending_availability", "available": True},
            ],
        ),
        effect_rule(
            "leave_frog_resort",
            families=["escape", "leave", "drive", "travel"],
            locations=["resort_boundary"],
            target_kind="location",
            target_id="outside",
            option_id="leave-now",
            hints=["独自离开度假村", "放弃调查后返回城市"],
            effects=[
                {"type": "enter_location", "location_id": "outside"},
                reveal("escaped_unresolved"),
                {"type": "mark_core_resolved"},
                {"type": "set_ending_availability", "available": True},
            ],
        ),
        effect_rule(
            "accept_messengers_happiness",
            families=["accept", "surrender", "stay"],
            locations=["resort_reception"],
            target_kind="entity",
            target_id="messenger",
            option_id="choose-happiness",
            hints=["明确选择留下", "接受信使的幸福"],
            effects=[
                reveal("accepted_happiness"),
                {"type": "mark_core_resolved"},
                {"type": "set_ending_availability", "available": True},
            ],
        ),
    ]
    rules.append(
        event_rule(
            "night_ritual_begins",
            event_type="time.point_entered",
            conditions=[
                time_of_day_is("night"),
                state_is("night_ritual", "active", False),
            ],
            effects=[
                set_state("night_ritual", "active", True),
                reveal("night_has_fallen"),
            ],
        )
    )
    rules.append(
        event_rule(
            "final_debate_becomes_available",
            event_type="information.revealed",
            conditions=[
                info_is("messenger_happiness_logic"),
                info_is("frogs_were_people"),
                state_is("final_debate", "available", False),
            ],
            effects=[set_state("final_debate", "available", True)],
        )
    )
    return rules


def build_module() -> dict[str, Any]:
    """生成第三个预设模组的完整 V3 权威内容。"""

    locations = [
        ("lane_manor", "site", "莱恩庄园", "寻人委托开始的庄园会客厅。"),
        (
            "pretrip_investigation",
            "site",
            "老林地周边村镇",
            "村民、警局档案和地方机构提供互相印证的线索。",
        ),
        ("forest_road", "connector", "老林地碎石路", "通往度假村的潮湿林间道路。"),
        (
            "frog_resort",
            "site",
            "蛙蛙度假村",
            "被雾气与老林环绕的田园度假村。沿碎石路望去，一栋醒目的两层别墅坐落在"
            "修剪整齐的草坪后方；别墅正门通向一层接待大厅，附近还能看到通往蛙鸣泉"
            "与度假村边界的小径。",
        ),
        ("resort_villa", "region", "度假村别墅", "接待、客房和员工区域所在的两层别墅。"),
        ("resort_ground_floor", "region", "别墅一层", "接待大厅与餐厅厨房所在楼层。"),
        ("resort_second_floor", "region", "别墅二层", "客房与非公开员工区域所在楼层。"),
        ("resort_reception", "room", "一层接待大厅", "卡通青蛙木牌后的明亮接待区。"),
        ("guest_room", "room", "客房", "整洁舒适，却处处重复幸福口号。"),
        ("dining_kitchen", "room", "用餐区与厨房", "所有汤水都带着蛙鸣泉的微光。"),
        ("frog_pond", "site", "蛙鸣泉", "度假村中心、聚集大量青蛙的池塘。"),
        (
            "crystal_shore",
            "site",
            "水晶池岸",
            "调查员将梦境水晶带上岸后，才形成的结局行动位置。",
        ),
        ("staff_area", "room", "员工区", "堆放制服、传单和员工纸条的非公开区域。"),
        ("storage_room", "room", "二楼杂物间", "堆满甜腻营养液桶的房间。"),
        ("messenger_bedroom", "room", "信使卧室", "保存信使私人笔记的简单卧室。"),
        ("resort_boundary", "connector", "度假村边界", "雾气包围的返程道路。"),
        ("outside", "site", "城郊道路", "离开度假村后的现实道路。"),
    ]
    parent_by_id = {
        "resort_villa": "frog_resort",
        "resort_ground_floor": "resort_villa",
        "resort_second_floor": "resort_villa",
        "resort_reception": "resort_ground_floor",
        "dining_kitchen": "resort_ground_floor",
        "guest_room": "resort_second_floor",
        "staff_area": "resort_second_floor",
        "storage_room": "resort_second_floor",
        "messenger_bedroom": "resort_second_floor",
        "frog_pond": "frog_resort",
        "crystal_shore": "frog_resort",
        "resort_boundary": "frog_resort",
    }
    aliases_by_id = {
        "resort_reception": ["度假村别墅", "别墅", "别墅入口"],
    }
    location_payloads = [
        {
            "id": item_id,
            "kind": kind,
            "name": name,
            "player_visible_name": name,
            "player_visible_description": description,
            **({"aliases": aliases_by_id[item_id]} if item_id in aliases_by_id else {}),
            "parent_location_id": parent_by_id.get(item_id),
            "plot_relevance": True,
            "lifecycle": "session",
        }
        for item_id, kind, name, description in locations
    ]

    edges: list[dict[str, Any]] = []

    def connect(
        edge_id: str,
        source: str,
        target: str,
        *,
        gated_by: str | None = None,
        conditions: list[dict[str, Any]] | None = None,
    ) -> None:
        forward: dict[str, Any] = {
            "id": edge_id,
            "from_location_id": source,
            "to_location_id": target,
            "kind": "private" if gated_by else "public_network",
            "traversal": "gated" if gated_by else "automatic",
            "visibility": "public",
        }
        if gated_by:
            forward["access_point_id"] = gated_by
        if conditions:
            forward["conditions"] = conditions
        edges.append(forward)
        edges.append(
            {
                "id": f"{edge_id}_back",
                "from_location_id": target,
                "to_location_id": source,
                "kind": "public_network",
                "traversal": "automatic",
                "visibility": "public",
            }
        )

    connect("manor_to_investigation", "lane_manor", "pretrip_investigation")
    connect("investigation_to_forest", "pretrip_investigation", "forest_road")
    connect("forest_to_resort", "forest_road", "frog_resort")
    # `resort_villa` and the two floor nodes are breadcrumb-only containment
    # ancestors.  Travel edges must land on rooms where play can actually take
    # place, otherwise entering the villa/upstairs leaves the actor stranded on
    # an abstract hierarchy node.
    connect("resort_to_reception", "frog_resort", "resort_reception")
    connect("reception_to_dining", "resort_reception", "dining_kitchen")
    connect("reception_stairs_to_guest", "resort_reception", "guest_room")
    connect("resort_to_pond", "frog_resort", "frog_pond")
    connect(
        "pond_to_crystal_shore",
        "frog_pond",
        "crystal_shore",
        conditions=[state_is("dream_crystal", "retrieved", True)],
    )
    connect("resort_to_boundary", "frog_resort", "resort_boundary")
    connect(
        "reception_to_staff",
        "resort_reception",
        "staff_area",
        gated_by="staff_door",
        conditions=[state_is("staff_door", "open", True)],
    )
    connect(
        "guest_to_staff",
        "guest_room",
        "staff_area",
        gated_by="staff_door",
        conditions=[state_is("staff_door", "open", True)],
    )
    connect("staff_to_storage", "staff_area", "storage_room")
    connect("staff_to_bedroom", "staff_area", "messenger_bedroom")
    connect("boundary_to_outside", "resort_boundary", "outside")

    return {
        "content_schema_version": 3,
        "module_id": "happy-frog-village",
        "version": "3.0.0",
        "world_ref": "coc-7e",
        "background": (
            "默认采用现代城郊。莱恩夫妇委托调查员寻找失踪的儿子詹姆斯，线索指向"
            "不存在于官方记录的蛙蛙度假村。叙事从温馨田园与整齐笑容逐渐滑向梦境、"
            "身体异变和选择权被剥夺的恐怖；信使本体、青蛙来源和水晶弱点只能随权威"
            "信息揭示。"
        ),
        "information": build_information(),
        "knowledge_goals": [
            {
                "id": "understand_resort_truth",
                "target_information_ids": [
                    "messenger_happiness_logic",
                    "frogs_were_people",
                    "crystal_is_power_core",
                ],
                "completion": "any",
                "required_for_core_resolution": False,
            },
            {
                "id": "choose_frog_village_outcome",
                "target_information_ids": [
                    "messenger_convinced",
                    "crystal_destroyed",
                    "escaped_unresolved",
                    "accepted_happiness",
                ],
                "completion": "any",
                "required_for_core_resolution": True,
            },
        ],
        "entities": build_entities(),
        "locations": location_payloads,
        "location_edges": edges,
        "rules": build_rules(),
        "core_resolution": {
            "required_goal_ids": ["choose_frog_village_outcome"],
            "completion": "all",
        },
        "ending_policy": {
            "allow_continue_after_core_resolution": True,
            "require_no_pending_action": True,
            "allow_grounded_variations": True,
            "facets": ["chosen_happiness", "james_fate", "victims_fate", "resort_fate"],
        },
        "ending_anchors": [
            {
                "id": "persuade_messenger_and_rescue_james",
                "tone": "hopeful",
                "required_fact_refs": [
                    "messenger_convinced",
                    "victims_released",
                    "james_returns_home",
                ],
                "forbidden_claims": [
                    "uncommitted_actor_stat_change",
                    "uncommitted_death",
                ],
            },
            {
                "id": "break_crystal_and_wake_victims",
                "tone": "harrowing",
                "required_fact_refs": ["crystal_destroyed", "victims_released"],
                "forbidden_claims": [
                    "uncommitted_actor_stat_change",
                    "invented_battle_result",
                ],
            },
            {
                "id": "accept_eternal_happiness",
                "tone": "uncanny",
                "required_fact_refs": ["accepted_happiness"],
                "forbidden_claims": [
                    "automatic_character_retirement",
                    "unconfirmed_transformation",
                ],
            },
            {
                "id": "leave_before_resolving_mystery",
                "tone": "ominous",
                "required_fact_refs": ["escaped_unresolved"],
                "forbidden_claims": [
                    "james_rescued",
                    "resort_destroyed",
                    "victims_released",
                ],
            },
            {
                "id": "force_james_out_and_lose_him",
                "tone": "tragic",
                "required_fact_refs": ["james_forced_removal_tragedy"],
                "forbidden_claims": [
                    "james_rescued",
                    "james_returned_alive",
                    "mission_completed_successfully",
                ],
            },
        ],
        "presentation": {
            "title": "幸福蛙蛙村",
            "name_en": "Happy Frog Village",
            "synopsis": "受托寻找失踪青年后，调查员来到一座以幸福为名的林间度假村，在甜美梦境、身体异变与自由选择之间追查真相。",
            "players_min": 1,
            "players_max": 4,
            "difficulty": 2,
            "estimated_duration": "4-6 小时",
            "story_label": "HAPPY FROG VILLAGE",
            "subtitle": "甜美梦境中的选择",
            "authors": ["一只小小信"],
            "tags": ["现代", "调查", "多结局", "心理恐怖"],
            "player_intro_pages": [
                {
                    "title": "内容提示",
                    "content": "本模组包含失踪、精神影响、身体异变、成瘾暗示、受害者失去自主、自杀后果，以及由玩家明确选择的留下结局。开始前请确认边界与安全工具。",
                },
                {
                    "title": "调查员准备",
                    "content": "适合 1-4 名调查员。推荐图书馆使用、侦查、心理学、精神分析、博物学、意志、体质和说服类技能。关键真相均有重试或替代来源。",
                },
                {
                    "title": "寻人委托",
                    "content": "企业家理查德·莱恩的儿子詹姆斯失踪一周。唯一线索是一张邀请人前往城郊寻找幸福的度假村传单。莱恩夫妇请你们找到他，并尽可能安全地带他回来。",
                },
            ],
        },
        "initial_state": {
            "start_location_id": "lane_manor",
            "default_actor_placement": {"location_id": "lane_manor"},
            "revealed_information_ids": ["commission_received", "frog_resort_flyer"],
            "start_time_point_id": "hour_12",
        },
        "world_profile": {
            "era": "现代（可由主持人改编到 1920 年代）",
            "region": "调查员所在城市近郊的老林地",
            "technology_level": "现代日常技术",
            "tone": "温馨田园逐步滑向甜美、潮湿且剥夺选择的诡异",
            "forbidden_content": [
                "提前揭示信使本体或水晶弱点",
                "用 Narrator 文本提交 HP、SAN、死亡或永久退役",
                "虚构逐角色四阶段变异已被运行时提交",
                "把未发生的战斗写成既成事实",
                "在詹姆斯尚未解除信使影响时把强行带离叙述为安全救援",
            ],
        },
        "time_policy": {
            "default_points": [
                {"id": "hour_08", "hour_of_day": 8, "order": 0},
                {"id": "hour_12", "hour_of_day": 12, "order": 1},
                {"id": "hour_18", "hour_of_day": 18, "order": 2},
                {"id": "hour_22", "hour_of_day": 22, "order": 3},
            ],
            "storage_precision": "hour",
            "progression": "host_controlled_discrete",
            "actions_per_point": "multiple",
        },
    }


def provenance(module: dict[str, Any]) -> dict[str, Any]:
    """记录结构化对象对应的 python-docx 段落索引。"""

    location_sources = {
        "lane_manor": [47, 50, 51, 53, 55, 57],
        "pretrip_investigation": [69, 72, 74, 77, 85, 94],
        "forest_road": [99, 100, 104, 105],
        "frog_resort": [131, 132, 133, 138, 195, 196, 239, 424],
        "resort_villa": [138, 140, 146, 195, 196, 206, 301, 305, 308],
        "resort_ground_floor": [138, 140, 146, 148, 206, 207, 212, 213],
        "resort_second_floor": [195, 201, 203, 204, 301, 305, 308],
        "resort_reception": [131, 138, 140, 146, 148],
        "guest_room": [195, 201, 203, 204],
        "dining_kitchen": [206, 212, 213, 215, 235, 236],
        "frog_pond": [239, 244, 246, 248, 251, 312, 313],
        "crystal_shore": [316, 317, 318, 320, 321, 322, 447, 448, 449, 450],
        "staff_area": [301, 302, 303],
        "storage_room": [305, 306],
        "messenger_bedroom": [308, 309, 310],
        "resort_boundary": [424, 425, 431, 432],
        "outside": [431, 432, 434],
    }
    information_sources = {
        "commission_received": [50, 51, 53, 55, 57],
        "frog_resort_flyer": [33, 34, 35, 36, 37, 38, 39, 57, 69, 70],
        "flyer_is_hand_drawn": [41],
        "missing_people_pattern": [74, 75, 77, 79, 80, 81, 82],
        "villagers_shared_dreams": [85, 86, 88, 90, 92],
        "resort_has_no_registration": [94, 95, 96, 97],
        "ezra_warning": [
            99,
            100,
            104,
            105,
            111,
            112,
            114,
            116,
            117,
            119,
            120,
            121,
            122,
            123,
            124,
        ],
        "staff_are_conditioned": [140, 144, 154, 155, 156, 157, 161],
        "messenger_happiness_logic": [
            148,
            149,
            151,
            152,
            298,
            299,
            324,
            325,
            326,
            361,
            467,
            468,
        ],
        "james_refuses_home": [156, 163, 164, 165, 166, 167, 168, 169],
        "james_resists_forced_removal": [167, 168, 169],
        "james_forced_removal_tragedy": [171, 172, 173, 174, 175],
        "happiness_booklet_doctrine": [201],
        "guests_show_mutation": [
            182,
            183,
            185,
            187,
            189,
            203,
            204,
            278,
            284,
            286,
            288,
            290,
            291,
            292,
            293,
        ],
        "all_liquids_use_pond_water": [
            206,
            207,
            208,
            209,
            212,
            213,
            215,
            216,
            235,
            236,
            237,
        ],
        "water_causes_hallucinations": [
            218,
            219,
            220,
            222,
            223,
            225,
            226,
            227,
            229,
            230,
            232,
            233,
            251,
            252,
            254,
            255,
            257,
            258,
            259,
            261,
            262,
            264,
            266,
            268,
            269,
            271,
        ],
        "frogs_were_people": [239, 244, 246, 248, 249, 387, 388, 398],
        "staff_notes_confessions": [301, 302, 303],
        "messenger_origin_notes": [308, 309, 310],
        "night_has_fallen": [280, 281, 282, 312],
        "night_ritual_seen": [312, 313, 314],
        "crystal_is_power_core": [313, 316, 317, 320, 321, 322, 447],
        "crystal_retrieved": [316, 317, 318, 320, 321, 322],
        "debate_failed_hint": [324, 325, 326, 436, 437, 439],
        "messenger_convinced": [436, 437, 439, 441, 443, 444],
        "crystal_destroyed": [447, 448, 449, 450],
        "victims_released": [439, 443, 444, 447, 448, 449],
        "james_returns_home": [439, 444, 459, 461, 463, 464],
        "escaped_unresolved": [424, 425, 431, 432, 433, 434],
        "accepted_happiness": [452, 453, 455, 456],
    }
    rule_sources = {
        "accept_lane_commission": [50, 51, 53, 55, 57],
        "inspect_resort_flyer": [41],
        "research_missing_people": [74, 75, 77, 79, 80, 81, 82],
        "ask_villagers_about_dreams": [85, 86, 88, 90, 92],
        "calm_ezra": [
            99,
            100,
            104,
            105,
            111,
            112,
            114,
            116,
            117,
            119,
            120,
            121,
            122,
            123,
            124,
        ],
        "read_messenger_intent": [140, 144, 146, 148, 149, 151, 152],
        "talk_to_james": [163, 164, 165, 166, 167, 168, 169],
        "force_james_against_his_will": [167, 168, 169],
        "force_james_out_of_resort": [171, 172, 173, 174, 175],
        "read_happiness_booklet": [201],
        "inspect_mutating_guest": [203, 204, 278],
        "trace_kitchen_water": [212, 213, 215, 216, 235, 236, 237],
        "resist_happiness_water": [215, 216, 218, 219, 220, 222, 223, 229, 230],
        "study_dream_frogs": [239, 244, 246, 248, 249],
        "infiltrate_staff_area": [301, 302, 303],
        "read_staff_notes": [301, 302, 303],
        "read_messenger_notes": [308, 309, 310],
        "observe_night_ritual": [312, 313, 314],
        "retrieve_dream_crystal": [316, 317, 318, 320, 321, 322],
        "persuade_happiness_messenger": [324, 325, 326, 436, 437, 439, 443, 444],
        "destroy_dream_crystal": [447, 448, 449, 450],
        "leave_frog_resort": [424, 425, 431, 432, 433, 434],
        "accept_messengers_happiness": [452, 453, 455, 456],
        "night_ritual_begins": [280, 281, 282, 312],
        "final_debate_becomes_available": [239, 248, 298, 299, 324, 325, 326],
    }
    return {
        "_comment": "来源段落为 python-docx Document.paragraphs 的 0-based 索引，供人工逐项核验。",
        "source": "模组幸福蛙蛙村.docx",
        "paragraph_numbering": "python-docx Document.paragraphs 0-based index",
        "module_id": module["module_id"],
        "version": module["version"],
        "locations": location_sources,
        "information": information_sources,
        "rules": rule_sources,
        "knowledge_goals": {
            "understand_resort_truth": [239, 248, 309, 310, 312, 313, 321, 322],
            "choose_frog_village_outcome": [175, 424, 425, 431, 436, 439, 447, 452, 455],
        },
        "ending_anchors": {
            "persuade_messenger_and_rescue_james": [
                436,
                437,
                439,
                443,
                444,
                459,
                461,
                463,
                464,
            ],
            "break_crystal_and_wake_victims": [447, 448, 449, 450],
            "accept_eternal_happiness": [452, 453, 455, 456],
            "leave_before_resolving_mystery": [424, 425, 431, 432, 433, 434],
            "force_james_out_and_lose_him": [171, 172, 173, 174, 175],
        },
    }


def review_markdown(module: dict[str, Any], source_map: dict[str, Any]) -> str:
    """生成秘密隔离、能力收敛与人工复核清单。"""

    rows = []
    for key, label in (
        ("locations", "Location"),
        ("information", "Information"),
        ("rules", "Rule"),
        ("knowledge_goals", "KnowledgeGoal"),
        ("ending_anchors", "EndingAnchor"),
    ):
        rows.append(f"| {label} | {len(module[key])} | {len(source_map[key])} |")
    return f"""<!-- 本文件说明《幸福蛙蛙村》结构化改编的覆盖、降级与运行约束。 -->
# 《幸福蛙蛙村》ModuleContentV3 审查报告

## 发布身份

- `module_id`: `{module["module_id"]}`
- `version`: `{module["version"]}`
- `world_ref`: `{module["world_ref"]}`
- 原作者：一只小小信
- 权威来源：`模组幸福蛙蛙村.docx`
- 关联 Issue：#419
- 授权：合并前必须由人工 Reviewer 核验结构化改编和公开发布范围。

## 来源覆盖

| 对象 | 数量 | 已映射 |
| --- | ---: | ---: |
{chr(10).join(rows)}

## 稳定版主线

- 寻人委托、前期档案/村民调查、埃兹拉警告和度假村多地点调查均有正式目标。
- 信使笔记与夜间仪式是水晶真相的两条来源；关键失败不会永久关闭主线。
- 说服、水晶破坏和主动离开分别提交独立 Canon Information，再由 EndingDraft 选择锚点。
- 强行控制詹姆斯会先提交他的挣扎与呼救；未解除影响便把他带出度假村，会提交原文声明的戒断、自尽和任务失败结局。
- 接受幸福/成为员工只在玩家明确选择后开放，不自动提交角色永久退役。

## 明确降级

- 当前 Effect 没有逐角色任意 actor-state 写入，四阶段异变只保留来源事实、内容提示和共享证据，不能由 Narrator 声称已权威修改属性。
- 不实现 24 小时失败计数、惩罚骰依赖、任意 KP 技能、群体逐轮战斗、自由 HP/治疗或永久撕卡。詹姆斯在未解除影响时被强行带离所导致的死亡，是原文明确结局，只能由对应规则提交。
- 破坏核心收敛为调查、夜间观察、困难潜水和确定性破坏水晶，不虚构完整 Boss 战结果。
- 原文五个结局中，战斗击败与说服/破坏核心共用受害者恢复事实；不声明未执行的伤害或死亡。

## 秘密隔离

- `presentation` 不泄露信使本体、青蛙来源、水晶作用、员工身份或詹姆斯最终状态。
- Keeper-only 真相只在 `keeper_content` 和隐藏 Canon 状态中出现。
- EndingAnchor 禁止虚构角色属性、战斗胜利和未提交的救援或死亡；只有强行带离规则能够提交詹姆斯的来源死亡事实。

## 人工复核

- [ ] 授权凭证、作者署名和公开发布范围已核验
- [ ] 逐项核对来源段落、玩家安全文本和秘密文本
- [ ] 说服、水晶、独自离开、强行带离詹姆斯、失败重试与夜间时间链真实引擎回放通过
- [ ] 1-4 人房间候选隔离、目录、加载器和前端 E2E 通过
- [ ] 《追书人》《银之锁》运行测试无回归
"""


def main() -> None:
    """校验后写出稳定排序、UTF-8 编码的正式审查产物。"""

    module = build_module()
    content = ModuleContentV3.model_validate(module)
    report = validate_module_v3(content)
    if not report.is_valid:
        rendered = "; ".join(
            f"{issue.code}@{issue.path}: {issue.message}" for issue in report.errors
        )
        raise ValueError(f"ModuleContentV3 语义校验失败: {rendered}")
    capability_issues = audit_runtime_capabilities(content)
    if capability_issues:
        raise ValueError(f"运行能力审计失败: {capability_issues!r}")

    normalized = content.to_json_dict()
    source_map = provenance(normalized)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "module-content-v3.json").write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (OUTPUT_DIR / "module-content-provenance.json").write_text(
        json.dumps(source_map, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (OUTPUT_DIR / "module-content-review.md").write_text(
        review_markdown(normalized, source_map),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
