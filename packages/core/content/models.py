"""Content 层数据模型 —— 对应 master §4.3 ModulePack 完整 schema + §4.3.6 战斗/判定规则引擎结构。

只读、随模组导入生成，运行时不可变。字段名对齐 master TS 记法（camelCase），
落库时按 ADR-9 转 snake_case（见各表 ORM 模型，本文件只定义领域模型）。

Rule/Op/HookDef/VariableDef 虽然是"规则引擎"的词汇表，但它们描述的是内容作者
（或模组导入解析出来）写下的规则数据本身，不是引擎的运行时行为，故定义在
content 层——core/rules 从这里导入这些类型来解释/执行它们，符合模块拆分设计.md
"core/rules 依赖 core/content" 的方向（不是反过来）。
"""

from __future__ import annotations

from enum import Enum
from typing import Literal, Optional, Union

from pydantic import BaseModel, Field

# ===== §4.3.6.1~4.3.6.6 规则引擎词汇表（Content 拥有，Rules 引擎解释执行） =====


class HookDef(BaseModel):
    """流水线可挂载点。COC 7e 定死 12 个（见 master §4.3.6.1），六模组验证后视为收敛。"""

    name: str
    accepts: list[str]
    returns: Literal["void", "bool"] | str  # 具体 hook 返回的变量名，或 'void'/'bool'
    position: int


class VariableDef(BaseModel):
    """规则可读的内建变量表——引擎能力的边界，Rule.when 只能引用这里列出的变量。"""

    name: str  # 如 "self.HP" / "party.size"
    description: str = ""


RuleMode = Literal["append", "override", "forbid"]


class Op(BaseModel):
    """算子——六模组验证后已收敛的算子集合（见 master §4.3.6.3），用判别式字典表达。

    只落地骨架阶段用到的字段，具体算子类型（set/scale/add/absorb/forbid/force/
    applyCondition/spawn/trigger/oppose）留到规则引擎正式实现时按 kind 展开。
    """

    kind: str
    payload: dict = Field(default_factory=dict)


class Rule(BaseModel):
    hook: str
    when: str  # Expr 字符串，语法见 master §4.3.6.6
    then: Op
    mode: RuleMode
    priority: int = 0


# ===== §4.3.6.7 Character 运行时结构（挂在 characters 表，但结构由模组内容驱动） =====


class Effect(BaseModel):
    duration: Optional[str] = None  # DiceExpr，如 "1d10d"
    permanent: Optional[dict[str, str]] = None
    apply: Optional[str] = None  # ConditionId


class ConditionStage(BaseModel):
    n: int
    check: Optional[str] = None
    delta: Optional[dict[str, str]] = None
    set_: Optional[dict[str, int]] = Field(default=None, alias="set")
    desc: str


class Condition(BaseModel):
    id: str
    timer: Optional[dict[str, str]] = None  # {"after"|"every"|"at": Duration}
    check: Optional[str] = None  # SkillRef 或 Expr
    on_fail: Optional[Effect] = Field(default=None, alias="onFail")
    on_success: Optional[Effect] = Field(default=None, alias="onSuccess")
    stages: Optional[list[ConditionStage]] = None
    reversible_until: Optional[int] = Field(default=None, alias="reversibleUntil")
    repeat_until: Optional[str] = Field(default=None, alias="repeatUntil")
    desc: str  # 唯一自由文本子字段，不参与计算

    model_config = {"populate_by_name": True}


class LedgerEntry(BaseModel):
    """计数器/时间窗/累计封顶/周期回复四种形态之一，见 master §4.3.6.7。"""

    kind: Literal["counter_window", "timed_event", "capped", "regen"]
    payload: dict = Field(default_factory=dict)


# ===== §4.3.0 World =====


class AttributeDef(BaseModel):
    name: str
    roll_formula: Optional[str] = Field(default=None, alias="rollFormula")

    model_config = {"populate_by_name": True}


class ResourcePoolDef(BaseModel):
    key: str
    kind: Literal["formula", "conditional", "roll"]
    payload: dict = Field(default_factory=dict)


class SkillDef(BaseModel):
    id: str
    default_value: int = Field(default=0, alias="defaultValue")
    allocatable: Literal["normal", "occupation_only", "none"] = "normal"

    model_config = {"populate_by_name": True}


class CheckMechanicDef(BaseModel):
    kind: Literal["d100_roll_under"] = "d100_roll_under"
    critical_max: int = Field(default=5, alias="criticalMax")
    fumble_min: int = Field(default=96, alias="fumbleMin")

    model_config = {"populate_by_name": True}


class SanityMechanicDef(BaseModel):
    severity_table: dict[Literal["mild", "moderate", "severe", "extreme"], "SanLossSpec"] = Field(
        default_factory=dict, alias="severityTable"
    )
    """🆕 2026-07-11 补，供 core/ai.SanJudge 临场触发 SAN 时换算成确定性效果，见 AI编排详细设计 §2.2。"""

    model_config = {"populate_by_name": True}


class World(BaseModel):
    id: str
    name: str
    attributes: list[AttributeDef] = Field(default_factory=list)
    resource_pools: list[ResourcePoolDef] = Field(default_factory=list, alias="resourcePools")
    skill_catalog: list[SkillDef] = Field(default_factory=list, alias="skillCatalog")
    check_mechanic: CheckMechanicDef = Field(default_factory=CheckMechanicDef, alias="checkMechanic")
    sanity_mechanic: SanityMechanicDef = Field(default_factory=SanityMechanicDef, alias="sanityMechanic")
    narrative_genre: str = Field(default="", alias="narrativeGenre")
    hooks: list[HookDef] = Field(default_factory=list)
    variables: list[VariableDef] = Field(default_factory=list)
    world_rules: list[Rule] = Field(default_factory=list, alias="worldRules")

    model_config = {"populate_by_name": True}


# ===== §4.3.1 ModulePack =====


class ModuleMeta(BaseModel):
    id: str  # {source}:{authorOrBuiltin}:{slug}:{version}，见 §4.3.5
    title: str
    version: str
    authors: list[str] = Field(default_factory=list)
    players_min: int = Field(alias="playersMin")
    players_max: int = Field(alias="playersMax")
    difficulty: Literal[1, 2, 3, 4, 5]
    estimated_duration: Optional[str] = Field(default=None, alias="estimatedDuration")
    source: Literal["builtin", "imported"]

    model_config = {"populate_by_name": True}


EntityKind = Literal["npc", "monster", "item", "clue", "animal", "object"]


class StatBlock(BaseModel):
    attributes: Optional[dict[str, int]] = None
    hp: Optional[int] = None
    armor: Optional[int] = None

    model_config = {"extra": "allow"}


class Entity(BaseModel):
    """★ 统一实体：吸收原 Clue+NPC，新增 monster/item/animal/object（见 master §4.3.1「为什么合并」）。"""

    id: str
    kind: EntityKind
    name: str
    content: Optional[str] = None
    public_persona: Optional[str] = Field(default=None, alias="publicPersona")  # 🟢 可进 PlayerView
    secrets: Optional[str] = None  # 🔴 仅进 GodView，绝不进 PlayerView（通信铁律一）
    stats: Optional[StatBlock] = None
    state: dict[str, Union[bool, int, float, str]] = Field(default_factory=dict)
    rules: list[Rule] = Field(default_factory=list)
    is_core: Optional[bool] = Field(default=None, alias="isCore")
    intentional_single_path: bool = Field(default=False, alias="intentionalSinglePath")
    handout_asset_id: Optional[str] = Field(default=None, alias="handoutAssetId")

    model_config = {"populate_by_name": True}


SanKind = Literal["check", "flat", "direct", "max_reduce", "gain", "capped"]


class SanLossSpec(BaseModel):
    success: str  # 骰子表达式，如 "1d4"
    fail: str


class SanTrigger(BaseModel):
    id: str
    kind: SanKind
    source_tag: Optional[str] = Field(default=None, alias="sourceTag")
    condition: Optional[str] = None
    loss: Optional[SanLossSpec] = None

    model_config = {"populate_by_name": True}


class CheckOutcome(BaseModel):
    """模组内容里的"效果套餐"——命中 Checkpoint 某分支后的结果，跟运行时骰子结果
    CheckRollResult（core/rules）不是同一个类型，二者曾撞名，2026-07-11 已拆开。
    """

    narration_hint: str = Field(alias="narrationHint")
    grants_entity_ids: Optional[list[str]] = Field(default=None, alias="grantsEntityIds")
    san_loss: Optional[SanLossSpec] = Field(default=None, alias="sanLoss")
    scene_transition: Optional[str] = Field(default=None, alias="sceneTransition")

    model_config = {"populate_by_name": True}


class Checkpoint(BaseModel):
    id: str
    skill: str  # 技能名，或类别引用如 "@交涉"
    difficulty: Optional[Literal["regular", "hard", "extreme"]] = None  # 允许为空，见软判据与硬求值分离
    on_success: CheckOutcome = Field(alias="onSuccess")
    on_fail: CheckOutcome = Field(alias="onFail")
    hidden: bool = False

    model_config = {"populate_by_name": True}


class WinCondition(BaseModel):
    id: str
    expr: str  # 状态表达式，语法见 §4.3.6.6
    is_ending: bool = Field(alias="isEnding")
    text: str

    model_config = {"populate_by_name": True}


class InvestigatorTemplate(BaseModel):
    """预设角色卡（module_pregens）。"""

    id: str
    occupation: str
    name: str
    age: int
    attributes: dict[str, int] = Field(default_factory=dict)
    derived_stats: dict[str, int] = Field(default_factory=dict, alias="derivedStats")
    skills: dict[str, int] = Field(default_factory=dict)
    equipment: list[str] = Field(default_factory=list)
    backstory: Optional[str] = None

    model_config = {"populate_by_name": True}


class Asset(BaseModel):
    id: str
    type: Literal["map", "image"]
    ref: str  # 指向 blob_assets.storage_key
    scene_ref: Optional[str] = Field(default=None, alias="sceneRef")

    model_config = {"populate_by_name": True}


class SceneContent(BaseModel):
    """★ 取代旧 clueIds/checkpointIds/sanTriggerIds + reachableBy，见 master §4.3.1「为什么改」。"""

    kind: Literal["entity_present", "clue_access", "checkpoint", "san_trigger"]
    entity_id: Optional[str] = Field(default=None, alias="entityId")
    via: Optional[Literal["checkpoint", "npc_dialogue", "auto"]] = None
    via_ref: Optional[str] = Field(default=None, alias="viaRef")
    checkpoint_id: Optional[str] = Field(default=None, alias="checkpointId")
    san_trigger_id: Optional[str] = Field(default=None, alias="sanTriggerId")

    model_config = {"populate_by_name": True}


class Scene(BaseModel):
    id: str
    title: str
    description: str
    contents: list[SceneContent] = Field(default_factory=list)
    exits: list[str] = Field(default_factory=list)  # 可通向的其它 Scene id
    map_ref: Optional[str] = Field(default=None, alias="mapRef")

    model_config = {"populate_by_name": True}


class ModulePack(BaseModel):
    meta: ModuleMeta
    world_ref: str = Field(alias="worldRef")
    setting: str
    scenes: list[Scene] = Field(default_factory=list)
    entities: list[Entity] = Field(default_factory=list)
    checkpoints: list[Checkpoint] = Field(default_factory=list)
    san_triggers: list[SanTrigger] = Field(default_factory=list, alias="sanTriggers")
    pregens: list[InvestigatorTemplate] = Field(default_factory=list)
    assets: list[Asset] = Field(default_factory=list)
    win: list[WinCondition] = Field(default_factory=list)
    keeper_notes: Optional[str] = Field(default=None, alias="keeperNotes")

    model_config = {"populate_by_name": True}
