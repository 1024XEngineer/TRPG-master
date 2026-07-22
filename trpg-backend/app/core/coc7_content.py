"""COC7 建卡规则数据（issue #84 S1）：属性生成公式 + 技能基础值 + 职业目录，
原样移植自 trpg-frontend/src/data/{character-model,skills,occupations}.ts，
作为后端系统级权威源——`app/core/seed.py` 把这里的数据写入
`GameSystem.ruleset`，`GET /systems/{systemId}/ruleset` 最终返回的就是这份
数据（S2 阶段会在此基础上加计算/校验，S3 阶段前端改成消费这个接口）。

数据来源对照（2026-07-18 核对）：
- 属性：`ATTRIBUTE_LABELS`（8 项），生成公式取自 `character.py` 的
  `roll_attributes` 已有实现：STR/CON/DEX/APP/POW = 3d6*5，SIZ/INT/EDU =
  (2d6+6)*5。
- 技能：`ALL_SKILLS`，前端原样照抄 76 条；issue #84 S2 发现有 3 个职业引用了
  技能表里不存在的 id（navigate/carpentry/illusion，移植时的悬空引用），
  补齐后共 79 条，跟 COC7 规则书常说的"79 项"数字一致纯属巧合；PR #85 review
  又补了信用评级（credit-rating）这条一直缺失的技能，共 80 条。
- 职业：`ALL_OCCUPATIONS`，实际 30 个（同样如实照抄，不是 32 个）。前端的
  `icon` 字段是纯 UI 展示用的 emoji，不属于规则数据，未移植。
"""

from app.dto.game import (
    AgeRangeSpec,
    AttributePointBuyRules,
    AttributeSpec,
    OccupationSpec,
    RulesetRead,
    SkillChoiceSlot,
    SkillSpec,
)

COC7_ATTRIBUTES: list[AttributeSpec] = [
    AttributeSpec(key="STR", label="力量", generation="3d6*5"),
    AttributeSpec(key="CON", label="体质", generation="3d6*5"),
    AttributeSpec(key="POW", label="意志", generation="3d6*5"),
    AttributeSpec(key="DEX", label="敏捷", generation="3d6*5"),
    AttributeSpec(key="APP", label="外貌", generation="3d6*5"),
    AttributeSpec(key="SIZ", label="体型", generation="(2d6+6)*5"),
    AttributeSpec(key="INT", label="智力", generation="(2d6+6)*5"),
    AttributeSpec(key="EDU", label="教育", generation="(2d6+6)*5"),
    # 幸运：COC7 里独立掷 3d6*5，不由任何属性推导，也不参与职业技能点公式与
    # 技能基础值；但它是有状态、游戏中可被 `luck.spend` 消耗的属性，所以归在
    # 属性而不是衍生值里。
    # point_buy=False：COC7 里幸运只能掷，不能用属性点购买，所以它不参与
    # 点数购买法的预算与加点网格。
    AttributeSpec(key="LUCK", label="幸运", generation="3d6*5", point_buy=False),
]

# 点数购买法的约束（issue #96：此前只存在于前端代码里）。
#
# 🔴 budget=480 是**本项目的自订规则（house rule）**，不是笔误——COC7 官方的
# 点数购买法是 460 点分给 8 项属性。2026-07-20 明确拍板沿用 480，记在这里是
# 为了避免以后有人把它当规则错误"修"回 460。
# COC7 调查员年龄区间：年龄档从 15-19 起、到 80-89 止。
COC7_AGE_RANGE = AgeRangeSpec(min_value=15, max_value=89)

COC7_ATTRIBUTE_POINT_BUY = AttributePointBuyRules(
    budget=480,
    min_value=10,
    max_value=90,
    default_value=50,
)

COC7_SKILLS: list[SkillSpec] = [
    SkillSpec(
        id="fighting-brawl",
        name="格斗：斗殴",
        name_en="Fighting (Brawl)",
        base=25,
        category="combat",
    ),
    SkillSpec(
        id="fighting-sword", name="格斗：剑", name_en="Fighting (Sword)", base=20, category="combat"
    ),
    SkillSpec(
        id="fighting-axe", name="格斗：斧", name_en="Fighting (Axe)", base=15, category="combat"
    ),
    SkillSpec(
        id="fighting-spear", name="格斗：矛", name_en="Fighting (Spear)", base=20, category="combat"
    ),
    SkillSpec(
        id="fighting-whip", name="格斗：鞭", name_en="Fighting (Whip)", base=5, category="combat"
    ),
    SkillSpec(
        id="fighting-chain",
        name="格斗：链枷",
        name_en="Fighting (Flail)",
        base=10,
        category="combat",
    ),
    SkillSpec(
        id="fighting-knife", name="格斗：刀", name_en="Fighting (Knife)", base=25, category="combat"
    ),
    SkillSpec(
        id="firearm-handgun",
        name="射击：手枪",
        name_en="Firearms (Handgun)",
        base=20,
        category="combat",
    ),
    SkillSpec(
        id="firearm-rifle",
        # issue #114：中文名原来是「射击：步枪」，把霰弹枪吞掉了——COC7 里
        # Firearms (Rifle/Shotgun) 本来就是**一项**技能（英文名一直是对的）。
        # 后果不是"名字不好看"：导入 229 个职业时，「射击（步枪/霰弹枪）」被按
        # 中文名匹配，霰弹枪找不到对应技能而被报成缺失。
        name="射击：步枪/霰弹枪",
        name_en="Firearms (Rifle/Shotgun)",
        base=25,
        category="combat",
    ),
    SkillSpec(
        id="firearm-smg", name="射击：冲锋枪", name_en="Firearms (SMG)", base=15, category="combat"
    ),
    SkillSpec(
        id="firearm-machine-gun",
        name="射击：机枪",
        name_en="Firearms (Machine Gun)",
        base=10,
        category="combat",
    ),
    SkillSpec(
        id="firearm-bow", name="射击：弓", name_en="Firearms (Bow)", base=15, category="combat"
    ),
    SkillSpec(
        id="firearm-flamethrower",
        name="射击：火焰喷射器",
        name_en="Firearms (Flamethrower)",
        base=10,
        category="combat",
    ),
    SkillSpec(id="dodge", name="闪避", name_en="Dodge", base="DEX/2", category="combat"),
    SkillSpec(id="throw", name="投掷", name_en="Throw", base=20, category="combat"),
    SkillSpec(id="charm", name="取悦", name_en="Charm", base=15, category="social"),
    SkillSpec(id="fast-talk", name="话术", name_en="Fast Talk", base=5, category="social"),
    SkillSpec(id="intimidate", name="恐吓", name_en="Intimidate", base=15, category="social"),
    SkillSpec(id="persuade", name="说服", name_en="Persuade", base=10, category="social"),
    SkillSpec(id="psychology", name="心理学", name_en="Psychology", base=10, category="social"),
    SkillSpec(id="disguise", name="乔装", name_en="Disguise", base=5, category="social"),
    # PR #85 review #4：信用评级本来是校验逻辑里的孤立参数（没有对应技能、
    # complete 从不传），补成一条真正的技能——`_compute` 里会特殊处理它
    # （用职业信用区间校验，不套常规上限/加点池）。
    SkillSpec(
        id="credit-rating", name="信用评级", name_en="Credit Rating", base=0, category="social"
    ),
    SkillSpec(id="accounting", name="会计", name_en="Accounting", base=5, category="knowledge"),
    SkillSpec(
        id="anthropology", name="人类学", name_en="Anthropology", base=1, category="knowledge"
    ),
    SkillSpec(id="appraise", name="估价", name_en="Appraise", base=5, category="knowledge"),
    SkillSpec(id="archaeology", name="考古学", name_en="Archaeology", base=1, category="knowledge"),
    SkillSpec(id="history", name="历史", name_en="History", base=5, category="knowledge"),
    SkillSpec(id="law", name="法律", name_en="Law", base=5, category="knowledge"),
    SkillSpec(
        id="library-use", name="图书馆使用", name_en="Library Use", base=20, category="knowledge"
    ),
    SkillSpec(id="medicine", name="医学", name_en="Medicine", base=1, category="knowledge"),
    SkillSpec(id="occult", name="神秘学", name_en="Occult", base=5, category="knowledge"),
    SkillSpec(
        id="science-pharmacy",
        name="科学：药学",
        name_en="Science (Pharmacy)",
        base=1,
        category="knowledge",
    ),
    SkillSpec(
        id="science-biology",
        name="科学：生物学",
        name_en="Science (Biology)",
        base=1,
        category="knowledge",
    ),
    SkillSpec(
        id="science-chemistry",
        name="科学：化学",
        name_en="Science (Chemistry)",
        base=1,
        category="knowledge",
    ),
    SkillSpec(
        id="science-physics",
        name="科学：物理学",
        name_en="Science (Physics)",
        base=1,
        category="knowledge",
    ),
    SkillSpec(
        id="science-geology",
        name="科学：地质学",
        name_en="Science (Geology)",
        base=1,
        category="knowledge",
    ),
    SkillSpec(
        id="science-astronomy",
        name="科学：天文学",
        name_en="Science (Astronomy)",
        base=1,
        category="knowledge",
    ),
    SkillSpec(
        id="science-forensics",
        name="科学：法医学",
        name_en="Science (Forensics)",
        base=1,
        category="knowledge",
    ),
    SkillSpec(
        id="science-mathematics",
        name="科学：数学",
        name_en="Science (Mathematics)",
        base=10,
        category="knowledge",
    ),
    SkillSpec(
        id="science-engineering",
        name="科学：工程学",
        name_en="Science (Engineering)",
        base=1,
        category="knowledge",
    ),
    SkillSpec(
        id="science-botany",
        name="科学：植物学",
        name_en="Science (Botany)",
        base=1,
        category="knowledge",
    ),
    SkillSpec(
        id="science-zoology",
        name="科学：动物学",
        name_en="Science (Zoology)",
        base=1,
        category="knowledge",
    ),
    SkillSpec(
        id="science-cryptography",
        name="科学：密码学",
        name_en="Science (Cryptography)",
        base=1,
        category="knowledge",
    ),
    SkillSpec(
        id="science-metallurgy",
        name="科学：冶金学",
        name_en="Science (Metallurgy)",
        base=1,
        category="knowledge",
    ),
    SkillSpec(
        id="science-meteorology",
        name="科学：气象学",
        name_en="Science (Meteorology)",
        base=1,
        category="knowledge",
    ),
    SkillSpec(
        id="natural-world", name="博物学", name_en="Natural World", base=10, category="knowledge"
    ),
    SkillSpec(id="navigation", name="导航", name_en="Navigation", base=10, category="knowledge"),
    SkillSpec(
        id="cthulhu-mythos",
        name="克苏鲁神话",
        name_en="Cthulhu Mythos",
        base=0,
        category="knowledge",
    ),
    SkillSpec(id="listen", name="聆听", name_en="Listen", base=20, category="perception"),
    SkillSpec(id="spot-hidden", name="侦察", name_en="Spot Hidden", base=25, category="perception"),
    SkillSpec(id="track", name="追踪", name_en="Track", base=10, category="perception"),
    SkillSpec(id="climb", name="攀爬", name_en="Climb", base=20, category="physical"),
    SkillSpec(id="jump", name="跳跃", name_en="Jump", base=20, category="physical"),
    SkillSpec(id="swim", name="游泳", name_en="Swim", base=20, category="physical"),
    SkillSpec(id="ride", name="骑术", name_en="Ride", base=5, category="physical"),
    SkillSpec(id="stealth", name="潜行", name_en="Stealth", base=20, category="physical"),
    SkillSpec(id="drive-auto", name="汽车驾驶", name_en="Drive Auto", base=20, category="physical"),
    SkillSpec(
        id="drive-carriage",
        name="驾驶：马车",
        name_en="Drive (Carriage)",
        base=5,
        category="physical",
    ),
    SkillSpec(
        id="pilot-aircraft",
        name="驾驶：飞行器",
        name_en="Pilot (Aircraft)",
        base=1,
        category="physical",
    ),
    SkillSpec(
        id="pilot-boat", name="驾驶：船舶", name_en="Pilot (Boat)", base=1, category="physical"
    ),
    SkillSpec(
        id="pilot-spacecraft",
        name="驾驶：航天器",
        name_en="Pilot (Spacecraft)",
        base=1,
        category="physical",
    ),
    SkillSpec(id="survival", name="生存", name_en="Survival", base=10, category="physical"),
    SkillSpec(id="first-aid", name="急救", name_en="First Aid", base=30, category="technical"),
    SkillSpec(
        id="heavy-machinery",
        name="操作重型机械",
        name_en="Heavy Machinery",
        base=1,
        category="technical",
    ),
    SkillSpec(
        id="electrical-repair",
        name="电气维修",
        name_en="Electrical Repair",
        base=10,
        category="technical",
    ),
    SkillSpec(
        id="mechanical-repair",
        name="机械维修",
        name_en="Mechanical Repair",
        base=10,
        category="technical",
    ),
    SkillSpec(id="lock-smith", name="锁匠", name_en="Locksmith", base=1, category="technical"),
    SkillSpec(
        id="art-craft-1", name="艺术与手艺①", name_en="Art & Craft 1", base=5, category="technical"
    ),
    SkillSpec(
        id="art-craft-2", name="艺术与手艺②", name_en="Art & Craft 2", base=5, category="technical"
    ),
    SkillSpec(
        id="art-craft-3", name="艺术与手艺③", name_en="Art & Craft 3", base=5, category="technical"
    ),
    SkillSpec(
        id="computer-use", name="计算机使用", name_en="Computer Use", base=5, category="technical"
    ),
    SkillSpec(id="electronics", name="电子学", name_en="Electronics", base=1, category="technical"),
    SkillSpec(id="photography", name="摄影", name_en="Photography", base=5, category="technical"),
    SkillSpec(
        id="language-native", name="母语", name_en="Language (Own)", base="EDU", category="language"
    ),
    SkillSpec(
        id="language-foreign-1",
        name="外语①",
        name_en="Language (Foreign 1)",
        base=1,
        category="language",
    ),
    SkillSpec(
        id="language-foreign-2",
        name="外语②",
        name_en="Language (Foreign 2)",
        base=1,
        category="language",
    ),
    SkillSpec(
        id="language-foreign-3",
        name="外语③",
        name_en="Language (Foreign 3)",
        base=1,
        category="language",
    ),
    # issue #84 S2：S1 移植时发现工程师/艺术家两个职业引用了这 3 个不存在的
    # 技能 id（悬空引用），补上缺失的技能定义。
    # issue #114：这里原本还有一条 `navigate`「导航」，是 S2 补悬空引用时加的——
    # 但 `navigation`（同名、同基础值 10）当时已经存在于 knowledge 分类里，那次
    # 没查重，把「引用了不存在的 id」修成了「同一个技能有两个 id」。留着的后果是
    # 任何提到导航的职业都要在两个 id 里二选一，口径必然飘。已删除，引用改指
    # `navigation`。
    SkillSpec(
        id="carpentry",
        name="艺术与手艺（木工）",
        name_en="Art & Craft (Carpentry)",
        base=5,
        category="technical",
    ),
    SkillSpec(
        id="illusion",
        name="艺术与手艺（魔术）",
        name_en="Art & Craft (Illusion)",
        base=5,
        category="technical",
    ),
    # issue #114：扩充职业目录到 229 项时发现的目录缺口。这 8 项都是规则书里
    # 真实存在、且被多个职业当作本职技能引用的技能，此前整个技能表里没有——
    # 移植前端那 76 条时就漏了（前端只覆盖了 30 个职业用得到的那些）。
    #
    # 缺了它们的后果不只是"少几项技能"：比如「游民」的本职技能原文是「锁匠**或**
    # 妙手」，妙手没有 id，这个二选一槽就退化成只有一个候选，等于把玩家的选择
    # 悄悄拿掉了。
    #
    # 基础值取自规则表 `附表` sheet 里那串骰娘导入宏（`会计5人类学1估价5…`），
    # 不是凭印象填的；用同一串里的 `攀爬20`/`会计5` 与目录现有值交叉验证过。
    SkillSpec(
        id="sleight-of-hand",
        name="妙手",
        name_en="Sleight of Hand",
        base=10,
        category="technical",
    ),
    SkillSpec(
        id="animal-handling",
        name="动物驯养",
        name_en="Animal Handling",
        base=5,
        category="technical",
    ),
    SkillSpec(
        id="psychoanalysis",
        name="精神分析",
        name_en="Psychoanalysis",
        base=1,
        category="knowledge",
    ),
    SkillSpec(id="diving", name="潜水", name_en="Diving", base=1, category="technical"),
    SkillSpec(id="hypnosis", name="催眠", name_en="Hypnosis", base=1, category="knowledge"),
    SkillSpec(id="artillery", name="炮术", name_en="Artillery", base=1, category="combat"),
    SkillSpec(id="demolitions", name="爆破", name_en="Demolitions", base=1, category="technical"),
    SkillSpec(id="read-lips", name="读唇", name_en="Read Lips", base=1, category="perception"),
    # 「学识」专精族。规则表 `本职技能` sheet 有 `学识：` 行，9 个职业引用它
    # （学识（佛教）/（道教）/（神道教）/（阴阳道）…），而目录里整族都不存在。
    #
    # 建成三个编号槽，与 `艺术与手艺①②③`、`外语①②③` 同构——依据同样是规则表
    # `附表`：「学识的专业化应该具体并且不同寻常，例如：梦学识、死灵之书学识、
    # UFO学识、吸血鬼学识…」，即专精开放式、由玩家自填，不可能枚举成固定 id。
    # 基础值 1 跟外语族一致（COC7 里 Lore 与 Other Language 同为 01%）。
    # 229 个职业里唯二用到、而族内没枚举到的两个专精（伐木工的「格斗（链锯）」、
    # 探险家的「驾驶（热气球）」）。格斗族和驾驶族在目录里本来就是枚举式的，
    # 补两项比给它们单开一套槽模型更贴合现状。基础值随族内同类：格斗系非制式
    # 武器取 10（同链枷），驾驶族取 1。
    SkillSpec(
        id="fighting-chainsaw",
        name="格斗：链锯",
        name_en="Fighting (Chainsaw)",
        base=10,
        category="combat",
    ),
    SkillSpec(
        id="pilot-balloon",
        name="驾驶：热气球",
        name_en="Pilot (Balloon)",
        base=1,
        category="technical",
    ),
    SkillSpec(id="lore-1", name="学识①", name_en="Lore (1)", base=1, category="knowledge"),
    SkillSpec(id="lore-2", name="学识②", name_en="Lore (2)", base=1, category="knowledge"),
    SkillSpec(id="lore-3", name="学识③", name_en="Lore (3)", base=1, category="knowledge"),
]

# 职业目录：229 项，由 `scripts/coc7_occupations/` 下的管线从 COC7 规则表生成
# （issue #114）。**不要手改这一段**——改了会被下次生成覆盖，且失去可追溯性。
# 要改先改管线或 resolutions.json，再重新生成。
#
# 生成流程与每一步的理由见 `scripts/coc7_occupations/build_occupations.py`。
# 两遍独立推导共 64 条分歧：60 条口径分歧由 normalize_conventions.py 机械消解，
# 剩余 4 条（对拍后一致率 225/229，98%）逐条人工裁定，依据见 resolutions.json。
COC7_OCCUPATIONS: list[OccupationSpec] = [
    OccupationSpec(
        id=1,
        name="会计师",
        credit_min=30,
        credit_max=70,
        skill_points_formula="EDU*4",
        description=(
            "会计师可能在企业工作或作为自由会计师，为个体经营者和企业客户担任顾问。 他们是优"
            "秀的研究者，既勤奋又关注细节，能够通过仔细分析个人和企业事务历史记录、财务报表和"
            "其他记录支持其他调查员。"
        ),
        skill_ids=["accounting", "law", "library-use", "listen", "persuade", "spot-hidden"],
        choice_slots=[
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=None,
                label="任意其他两项个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=2,
        name="杂技演员",
        credit_min=9,
        credit_max=20,
        skill_points_formula="EDU*2+DEX*2",
        description=(
            "杂技演员可能是参加各级比赛(甚至奥运会)的业余运动员，也可能是专业的演员，在马戏"
            "团、嘉年华、歌舞团之类的地方作为娱乐业从业者工作。"
        ),
        skill_ids=["climb", "dodge", "jump", "spot-hidden", "swim", "throw"],
        choice_slots=[
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=None,
                label="任意两项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=3,
        name="演员-戏剧演员",
        credit_min=9,
        credit_max=40,
        skill_points_formula="EDU*2+APP*2",
        description=(
            "一般指舞台剧演员和电影演员。许多演员有相当深厚的文化素养，认为自己才是“正统”的"
            "，倾向于轻视电影业的商业活动。直到20 世纪后期电影业的地位提高，电影演员的薪酬"
            "增加，这种情况才发生改变。 电影业和电影明星一直是世界人民关注的焦点。许多明星一"
            "夜成名，在媒体的聚光灯下过着光鲜亮丽的生活。 在1920 年代，虽然全国都有大型"
            "剧院，美国的戏剧中心仍然是纽约城。英国的情况与之相近，戏剧的中心在伦敦，其他的剧"
            "团则在各郡作巡回演出。巡回剧团乘火车旅行，演出内容既包括新编剧目，也包括莎士比亚"
            "和其他人的传统剧目。有些剧团也会花时间去国外采风，通常是去加拿大、夏威夷、澳大利"
            "亚和欧洲大陆。 20 年代后期出现了有声电影，不少默片时代的明星难以适应有声电影"
            "的冲击，挥舞手臂的夸张扮演从此让位给了细致入微的角色特写。这段时间前期的明星包括"
            "约翰·加菲尔德和弗兰西斯·布什曼，后期则是贾莱·库珀和琼·克劳馥。"
        ),
        skill_ids=["disguise", "history", "psychology"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "fighting-brawl",
                    "fighting-sword",
                    "fighting-axe",
                    "fighting-spear",
                    "fighting-whip",
                    "fighting-chain",
                    "fighting-knife",
                ],
                label="格斗（任选一项专精）",
            ),
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="两项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=None,
                label="任意一项其他个人或时代特长",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["art-craft-1", "art-craft-2", "art-craft-3"],
                label="技艺（表演）",
            ),
        ],
    ),
    OccupationSpec(
        id=4,
        name="演员-电影演员",
        credit_min=20,
        credit_max=90,
        skill_points_formula="EDU*2+APP*2",
        description=(
            "一般指舞台剧演员和电影演员。许多演员有相当深厚的文化素养，认为自己才是“正统”的"
            "，倾向于轻视电影业的商业活动。直到20 世纪后期电影业的地位提高，电影演员的薪酬"
            "增加，这种情况才发生改变。 电影业和电影明星一直是世界人民关注的焦点。许多明星一"
            "夜成名，在媒体的聚光灯下过着光鲜亮丽的生活。 在1920 年代，虽然全国都有大型"
            "剧院，美国的戏剧中心仍然是纽约城。英国的情况与之相近，戏剧的中心在伦敦，其他的剧"
            "团则在各郡作巡回演出。巡回剧团乘火车旅行，演出内容既包括新编剧目，也包括莎士比亚"
            "和其他人的传统剧目。有些剧团也会花时间去国外采风，通常是去加拿大、夏威夷、澳大利"
            "亚和欧洲大陆。 20 年代后期出现了有声电影，不少默片时代的明星难以适应有声电影"
            "的冲击，挥舞手臂的夸张扮演从此让位给了细致入微的角色特写。这段时间前期的明星包括"
            "约翰·加菲尔德和弗兰西斯·布什曼，后期则是贾莱·库珀和琼·克劳馥。"
        ),
        skill_ids=["disguise", "drive-auto", "psychology"],
        choice_slots=[
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="两项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=None,
                label="任意两项其他个人或时代特长（如骑乘或格斗）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["art-craft-1", "art-craft-2", "art-craft-3"],
                label="技艺（表演）",
            ),
        ],
    ),
    OccupationSpec(
        id=5,
        name="事务所侦探、保安",
        credit_min=20,
        credit_max=45,
        skill_points_formula="EDU*2+MAX(STR,DEX)*2",
        description=(
            "世界上有许多著名的侦探机构，其中最著名的是平克顿和伯恩斯调查局(后来合并成一家公"
            "司)。这样的公司一般有两类工作人员：安保人员和调查人员。 企业或个人雇用安保人员"
            "来保护自己的资产和人员免受盗贼、刺客和绑匪的威胁。这些安保人员角色使用巡警的职业"
            "模板。调查人员则是便衣侦探，负责为公司客户解决各种异常事件、阻止谋杀事件、寻找失"
            "踪的人员等等。"
        ),
        skill_ids=["fighting-brawl", "law", "library-use", "psychology", "stealth", "track"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="一项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "firearm-handgun",
                    "firearm-rifle",
                    "firearm-smg",
                    "firearm-machine-gun",
                    "firearm-bow",
                    "firearm-flamethrower",
                ],
                label="射击（任选一项专精）",
            ),
        ],
    ),
    OccupationSpec(
        id=6,
        name="精神病医生（古典）",
        credit_min=10,
        credit_max=60,
        skill_points_formula="EDU*4",
        description=(
            "在1920 年代，“精神病医生”这个词专用来称呼治疗精神失常的医生(也就是早期的"
            "精神科医生)。精神分析在当时的美国鲜为人知，而且它的基本内容都是性生活和如厕训练"
            "之类令大众不齿的东西。精神病学，一种正规的从行为主义发展来的医学理论则要普及得多"
            "。精神病医生、精神科医生和神经科医生还经常爆发激烈的论战。"
        ),
        skill_ids=[
            "law",
            "listen",
            "medicine",
            "psychoanalysis",
            "psychology",
            "science-biology",
            "science-chemistry",
        ],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "language-foreign-1",
                    "language-foreign-2",
                    "language-foreign-3",
                ],
                label="外语（任一）",
            ),
        ],
    ),
    OccupationSpec(
        id=7,
        name="动物训练师",
        credit_min=10,
        credit_max=40,
        skill_points_formula="EDU*2+MAX(APP,POW)*2",
        description=(
            "动物训练师可能在电影工作室、巡回马戏团、马厩工作或自由工作。不管是训练导盲犬、狮"
            "子钻火圈，他们工作时基本要独自一人长时间近距离地照看这些动物。动物训练师可以像对"
            "人一样对动物使用「心理学」技能。"
        ),
        skill_ids=[
            "animal-handling",
            "jump",
            "listen",
            "natural-world",
            "psychology",
            "science-zoology",
            "stealth",
            "track",
        ],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=None,
                label="任意一项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=8,
        name="文物学家（原作向）",
        credit_min=30,
        credit_max=70,
        skill_points_formula="EDU*4",
        description=(
            "文物学家也许是调查员可以从事的最具有洛夫克拉夫特风格的职业：那些历久弥新的的卓越"
            "作品、湮没在古代传说中的神奇力量，总能使他们乐在其中。独立的收入使文物学家能够研"
            "究古旧晦涩的文物，或者根据自己的兴趣爱好集中探寻特别的种类。他们通常有着欣赏的眼"
            "光、敏锐的头脑，和讽刺无知、自大、贪婪者的愚蠢时尖酸刻薄的幽默。"
        ),
        skill_ids=["appraise", "history", "library-use", "spot-hidden"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["art-craft-1", "art-craft-2", "art-craft-3"],
                label="技艺（任一）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "language-foreign-1",
                    "language-foreign-2",
                    "language-foreign-3",
                ],
                label="外语（任选一门）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="一项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=None,
                label="任意一项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=9,
        name="古董商",
        credit_min=30,
        credit_max=50,
        skill_points_formula="EDU*4",
        description=(
            "古董商通常自己开店，从自己所在的地方转卖物品，或继续扩展业务范围，通过倒卖物品到"
            "城市商店赚取利润。"
        ),
        skill_ids=["accounting", "appraise", "drive-auto", "history", "library-use", "navigation"],
        choice_slots=[
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="两项社交技能（取悦、话术、恐吓、说服）",
            ),
        ],
    ),
    OccupationSpec(
        id=10,
        name="考古学家（原作向）",
        credit_min=10,
        credit_max=40,
        skill_points_formula="EDU*4",
        description=(
            "考古学家研究探索历史的痕迹。主要来说，是对人类历史相关的物质数据进行各种鉴识、检"
            "查、分析。这项工作包含辛苦细致的研究，更不必提情愿亲自下斗铲土的决心。 在192"
            "0 年代，成功的考古学家会被当成著名冒险家与探险家，名利双收。有人运用科学方法考"
            "古，不过更多的人对付老祖宗的秘密时喜好暴力破解的办法，甚至祭出炸药，这种碉堡了的"
            "办法现代人可是很难看得惯的。"
        ),
        skill_ids=[
            "appraise",
            "archaeology",
            "history",
            "library-use",
            "mechanical-repair",
            "spot-hidden",
        ],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "language-foreign-1",
                    "language-foreign-2",
                    "language-foreign-3",
                ],
                label="外语（任选一门）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "navigation",
                    "science-pharmacy",
                    "science-biology",
                    "science-chemistry",
                    "science-physics",
                    "science-geology",
                    "science-astronomy",
                    "science-forensics",
                    "science-mathematics",
                    "science-engineering",
                    "science-botany",
                    "science-zoology",
                    "science-cryptography",
                    "science-metallurgy",
                    "science-meteorology",
                ],
                label="导航或科学（任一：如化学、物理、地理等）",
            ),
        ],
    ),
    OccupationSpec(
        id=11,
        name="建筑师",
        credit_min=30,
        credit_max=70,
        skill_points_formula="EDU*4",
        description=(
            "建筑师掌握设计和营造建筑的知识，不论是个人房屋的改造还是造价数百万美元的地标工程"
            "。建筑师与项目经理紧密合作，负责监督施工全程。建筑师必须了解当地的规划法律，健康"
            "和安全法规，和基础的公众安全原则。他们既可以在大公司工作，也可以自由工作，这在很"
            "大程度上取决于信誉。 在1920 年代，许多人尝试在自家或小办公室单干。不过他们"
            "苦心创造的宏伟设计很少能卖得出去。 建筑师也可能专擅某一学科，比如军事建筑或景观"
            "工程等。"
        ),
        skill_ids=[
            "accounting",
            "language-native",
            "law",
            "persuade",
            "psychology",
            "science-mathematics",
        ],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["computer-use", "library-use"],
                label="计算机或图书馆",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["art-craft-1", "art-craft-2", "art-craft-3"],
                label="技艺（技术制图）",
            ),
        ],
    ),
    OccupationSpec(
        id=12,
        name="艺术家",
        credit_min=9,
        credit_max=50,
        skill_points_formula="EDU*2+MAX(DEX,POW)*2",
        description=(
            "艺术家在这里可以是画家，雕塑家等等。他们有时沈浸于自己虚幻的想象当中，有时又沐浴"
            "在激发热情和理解的灵感之下。不论是否天资优秀，艺术家的内心必须足够强大，这样才能"
            "战胜生涯起步时的障碍和挑剔的眼光，并且在自己小有名气以后继续努力。有些艺术家对物"
            "质生活是否丰富并不在乎，而有些则有着强烈的创业倾向。"
        ),
        skill_ids=["psychology", "spot-hidden"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["art-craft-1", "art-craft-2", "art-craft-3"],
                label="技艺（任一）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["history", "natural-world"],
                label="历史或自然（博物学）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="一项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "language-foreign-1",
                    "language-foreign-2",
                    "language-foreign-3",
                ],
                label="外语（任一）",
            ),
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=None,
                label="任意两项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=13,
        name="精神病院看护",
        credit_min=8,
        credit_max=20,
        skill_points_formula="EDU*2+MAX(STR,DEX)*2",
        description=(
            "尽管少数富有的人会选择私人疗养院，大多精神病患者最终会被安置到州县设置的定点医院"
            "。这些地方除了医生护士以外，还会有一支看护队伍。选聘看护的时候，力量和体格往往比"
            "医学知识更被看重。"
        ),
        skill_ids=["dodge", "fighting-brawl", "first-aid", "listen", "psychology", "stealth"],
        choice_slots=[
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="两项社交技能（取悦、话术、恐吓、说服）",
            ),
        ],
    ),
    OccupationSpec(
        id=14,
        name="运动员",
        credit_min=9,
        credit_max=70,
        skill_points_formula="EDU*2+MAX(STR,DEX)*2",
        description=(
            "运动员可能效力于职业的棒球、足球、板球或者篮球队伍。这支队伍也许是大联盟队伍，有"
            "着稳定工资，参加的比赛万人瞩目；或者是众多小联盟队伍之一，尤其是在1920 年代"
            "的棒球界。这些队伍往往寄于大联盟队伍篱下，各方面都受其管理，工资更是刚够运动员糊"
            "口又不至于让他们跳槽的水平。 成功的运动员在自己的专业领域会拥有相当的声誉——现"
            "今尤其如此，在世界各地都能看到体育明星和电影明星并肩站在红地毯上的场景。"
        ),
        skill_ids=["climb", "fighting-brawl", "jump", "ride", "swim", "throw"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="一项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=None,
                label="任意一项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=15,
        name="作家（原作向）",
        credit_min=9,
        credit_max=30,
        skill_points_formula="EDU*4",
        description=(
            "作家不同于记者，他们用文字定义和探讨人们的社会生活，尤其是人们的情感变化。他们的"
            "劳动通常孤立而又自我中心：虽然以前写作是个能稳拿工资的行当，但如今只靠写作发大财"
            "的人屈指可数。 作家的工作习惯相差极大。通常作家们会花费数月乃至数年的时间调查取"
            "材，为新书的创作做准备；然后闭门谢客，投入紧张的创作。"
        ),
        skill_ids=["history", "language-native", "library-use", "psychology"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["natural-world", "occult"],
                label="自然或神秘学",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "language-foreign-1",
                    "language-foreign-2",
                    "language-foreign-3",
                ],
                label="外语（任选一门）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=None,
                label="任意一项其他个人或时代特长",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["art-craft-1", "art-craft-2", "art-craft-3"],
                label="技艺（文学）",
            ),
        ],
    ),
    OccupationSpec(
        id=16,
        name="酒保",
        credit_min=8,
        credit_max=25,
        skill_points_formula="EDU*2+APP*2",
        description=(
            "酒保虽然不一定是酒吧的掌柜，却一定是所有客人的朋友。对客人们的好声气，一部分来说"
            "是出于他们的职业或者业务，而更多的来说则是达到目的的一种手段。 1920 年代，"
            "由于禁酒令的存在，酒保变成了非法的职业；但是遍地开花的黑酒吧又不能没有酒保，结果"
            "就是酒保仍然不愁找不到活干。"
        ),
        skill_ids=["accounting", "fighting-brawl", "listen", "psychology", "spot-hidden"],
        choice_slots=[
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="两项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=None,
                label="任意一项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=17,
        name="猎人",
        credit_min=20,
        credit_max=50,
        skill_points_formula="EDU*2+MAX(STR,DEX)*2",
        description=(
            "猎人是优秀的追踪者和狩猎者，通常靠为富裕的客户捕猎为生。绝大多数猎人会对地球上某"
            "一个部分的情况烂熟于心，比如加拿大森林、非洲草原等等。有些人可能从事盗猎活动，例"
            "如为私人收藏家捕捉珍稀动物，或者贩卖受保护的动物和违反道德的动物制品，如兽皮、象"
            "牙之类——虽然1920 年代大多数国家这些活动都不算违法。 尽管“王牌猎人”是最"
            "典型的类型，不过在加拿大育空的深山老林里打驼鹿和熊为生的土著人也可以算是猎人。"
        ),
        skill_ids=["natural-world", "navigation", "stealth", "track"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "firearm-handgun",
                    "firearm-rifle",
                    "firearm-smg",
                    "firearm-machine-gun",
                    "firearm-bow",
                    "firearm-flamethrower",
                ],
                label="射击（任选一种专精）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["listen", "spot-hidden"],
                label="聆听或侦查",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "language-foreign-1",
                    "language-foreign-2",
                    "language-foreign-3",
                ],
                label="外语或生存（任一）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["science-biology", "science-botany"],
                label="科学（生物学或植物学）",
            ),
        ],
    ),
    OccupationSpec(
        id=18,
        name="书商",
        credit_min=20,
        credit_max=40,
        skill_points_formula="EDU*4",
        description=(
            "书商可能拥有自己的店面或者利基(小众)邮购服务，也可能辗转全国甚至海外专门经销书"
            "籍。许多人拥有富有的，能提供利润丰厚又稀罕的工作的固定客户。"
        ),
        skill_ids=[
            "accounting",
            "appraise",
            "drive-auto",
            "history",
            "language-native",
            "library-use",
        ],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "language-foreign-1",
                    "language-foreign-2",
                    "language-foreign-3",
                ],
                label="外语（任选一门）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="一项社交技能（取悦、话术、恐吓、说服）",
            ),
        ],
    ),
    OccupationSpec(
        id=19,
        name="赏金猎人",
        credit_min=9,
        credit_max=30,
        skill_points_formula="EDU*2+MAX(STR,DEX)*2",
        description=(
            "赏金猎人捉拿罪犯并将他们交给正义去审判。最常见的情况是受保释人的委托去缉捕逃狱者"
            "。赏金猎人们为了自己的猎物可以不择手段，几乎不会考虑其他人的正当权益之类细枝末节"
            "的东西。 非法闯入、威胁、肢体暴力，都是赏金猎人屡试不爽的秘技。现在这些秘技还包"
            "括了电话窃听、黑客操作和其他的秘密监控。 (译注：所谓保释业者。向法院交纳保释金"
            "，可以在审判之前免受收押；若被保释者按时接受审判，法院会退还保释金。保释金数额较"
            "大，故有保释业者以提供保释金收取手续费为业。)"
        ),
        skill_ids=["drive-auto", "law", "psychology", "stealth", "track"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["electronics", "electrical-repair"],
                label="电子学或电气维修",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "fighting-brawl",
                    "fighting-sword",
                    "fighting-axe",
                    "fighting-spear",
                    "fighting-whip",
                    "fighting-chain",
                    "fighting-knife",
                    "firearm-handgun",
                    "firearm-rifle",
                    "firearm-smg",
                    "firearm-machine-gun",
                    "firearm-bow",
                    "firearm-flamethrower",
                ],
                label="格斗或射击（任选一种专精）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="一项社交技能（取悦、话术、恐吓、说服）",
            ),
        ],
    ),
    OccupationSpec(
        id=20,
        name="拳击手、摔跤手",
        credit_min=9,
        credit_max=60,
        skill_points_formula="EDU*2+STR*2",
        description=(
            "拳击手和摔跤手各分为职业和业余两种。 职业拳击手和职业摔角手的活动由外部利益支持"
            "的贸助人安排，并有合同约束。他们还要进行全日制的工作和训练。 业余拳击的竞赛种类"
            "非常丰富，同时它也是那些想成为职业拳手的人的训练场。不过也有业余和准职业的选手靠"
            "参加黑市拳击赛谋生，举办这些比赛的通常是本地的黑社会或者是从中渔利的庄家。"
        ),
        skill_ids=["dodge", "fighting-brawl", "intimidate", "jump", "psychology", "spot-hidden"],
        choice_slots=[
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=None,
                label="任意两项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=21,
        name="管家、男仆、女仆",
        credit_min=9,
        credit_max=40,
        skill_points_formula="EDU*4",
        description="",
        skill_ids=["first-aid", "listen", "psychology", "spot-hidden"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["accounting", "appraise"],
                label="会计或估价",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["art-craft-1", "art-craft-2", "art-craft-3"],
                label="技艺（任一：如烹饪、裁缝、理发）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "language-foreign-1",
                    "language-foreign-2",
                    "language-foreign-3",
                ],
                label="外语（任选一门）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=None,
                label="任意一项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=22,
        name="神职人员",
        credit_min=9,
        credit_max=60,
        skill_points_formula="EDU*4",
        description=(
            "神职人员通常担任一个教区的牧师，或是经过分配外出传教，尤其是去国外(见传教士)。"
            " 不同的教会工作的侧重点和组织结构各不相同，如天主教会的牧师可能上升到主教、大主"
            "教和红衣主教，而一个卫理公会的牧师则会升职到教区主管和主教。 许多神职人员都接受"
            "忏悔(不仅仅是天主教)。虽然不能透露忏悔的内容，但是要怎样利用它们就全凭他们自己"
            "了。 有些教职人员在教堂接受医生、律师、学者的专业培训。这样的调查员应该选择最符"
            "合自己工作的职业模板。"
        ),
        skill_ids=["accounting", "history", "library-use", "listen", "psychology"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "language-foreign-1",
                    "language-foreign-2",
                    "language-foreign-3",
                ],
                label="外语（任选一门）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="一项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=None,
                label="任意一项其他技能",
            ),
        ],
    ),
    OccupationSpec(
        id=23,
        name="程序员、电子工程师（现代）",
        credit_min=10,
        credit_max=70,
        skill_points_formula="EDU*4",
        description=(
            "计算器程序员通常是设计、编写、测试、调试和维护计算器程序源代码的职业。他们精通从"
            "形式逻辑到系统平台(程序运行环境)的各种知识，可能是自由工作者，也可能供职于软件"
            "开发部门。 计算器技术人员负责计算器系统和网络的开发和维护工作，经常与其他人员("
            "如项目经理)合作来保证系统的完整稳定和正常提供所需功能。类似的职业还包括数据库管"
            "理员、系统管理员、网络管理员、多媒体开发人员、软件工程师、网络管理员等。"
        ),
        skill_ids=[
            "computer-use",
            "electrical-repair",
            "electronics",
            "library-use",
            "science-mathematics",
            "spot-hidden",
        ],
        choice_slots=[
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=None,
                label="任意两项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=24,
        name="黑客/骇客（现代）",
        credit_min=10,
        credit_max=70,
        skill_points_formula="EDU*4",
        description=(
            "计算器黑客利用计算器和计算器网络为手段，进行干扰或破坏以达成政治目的(有时被称为"
            "“政治黑客”)或获取非法利益。达成目标的手段主要是非法入侵计算器和其他用户帐户，"
            "目的则可能包括篡改网页、人肉搜索、盗取身份信息、垃圾邮件炸弹、拒绝服务攻击等等。"
        ),
        skill_ids=[
            "computer-use",
            "electrical-repair",
            "electronics",
            "library-use",
            "spot-hidden",
        ],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="一项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=None,
                label="任意两项其他技能",
            ),
        ],
    ),
    OccupationSpec(
        id=25,
        name="牛仔",
        credit_min=9,
        credit_max=20,
        skill_points_formula="EDU*2+MAX(STR,DEX)*2",
        description=(
            "牛仔在西部的牧区和牧场工作。有些人拥有自己的牧场，更多的则是在各处打工为生。想赚"
            "大钱的牛仔会去冒着丢胳膊少腿乃至送命的危险参加牛仔巡回赛，通过旅行获取名誉。 在"
            "1920 年代，一些牛仔能在好莱坞找到西部片替身演员和群众演员的工作，例如怀特·"
            "厄普就曾为西部电影担任顾问。在现代，有些牧场也对想要体验一把牛仔生活的游客开放。"
        ),
        skill_ids=["dodge", "jump", "ride", "survival", "throw", "track"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "fighting-brawl",
                    "fighting-sword",
                    "fighting-axe",
                    "fighting-spear",
                    "fighting-whip",
                    "fighting-chain",
                    "fighting-knife",
                    "firearm-handgun",
                    "firearm-rifle",
                    "firearm-smg",
                    "firearm-machine-gun",
                    "firearm-bow",
                    "firearm-flamethrower",
                ],
                label="格斗或射击（任选一种专精）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["first-aid", "natural-world"],
                label="急救或自然",
            ),
        ],
    ),
    OccupationSpec(
        id=26,
        name="工匠",
        credit_min=10,
        credit_max=40,
        skill_points_formula="EDU*2+DEX*2",
        description=(
            "工匠也可能被人叫做师傅或大师，是擅长对各种材料进行手工加工的人。通常都是才能出众"
            "的人，有的凭借自己的艺术作品出名，有的则会服务于自己的小区。 可能的行当包括：家"
            "具、珠宝、钟表、陶艺、锻造、纺织、书法、裁缝、木工、书籍装裱、玩具制造、彩色玻璃"
            "吹制等等。"
        ),
        skill_ids=["accounting", "mechanical-repair", "natural-world", "spot-hidden"],
        choice_slots=[
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=["art-craft-1", "art-craft-2", "art-craft-3"],
                label="技艺（任二）",
            ),
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=None,
                label="任意两项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=27,
        name="罪犯-刺客",
        credit_min=30,
        credit_max=60,
        skill_points_formula="EDU*2+MAX(STR,DEX)*2",
        description=(
            "杀手是地下世界的冷血夺命者。这是一项严谨的活计，他们从外地受雇杀人，接近目标，果"
            "断下手，又迅速离开。杀手通常很难融入社会，因为很多杀手行为总是很刻板，其他人很容"
            "易以为他们不近人情。但是另一方面，他们也会结婚生子，在其他方面和普通人没有什么不"
            "同。"
        ),
        skill_ids=[
            "disguise",
            "electrical-repair",
            "lock-smith",
            "mechanical-repair",
            "psychology",
            "stealth",
        ],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "fighting-brawl",
                    "fighting-sword",
                    "fighting-axe",
                    "fighting-spear",
                    "fighting-whip",
                    "fighting-chain",
                    "fighting-knife",
                ],
                label="格斗（任选一种专精）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "firearm-handgun",
                    "firearm-rifle",
                    "firearm-smg",
                    "firearm-machine-gun",
                    "firearm-bow",
                    "firearm-flamethrower",
                ],
                label="射击（任选一种专精）",
            ),
        ],
    ),
    OccupationSpec(
        id=28,
        name="罪犯-银行劫匪",
        credit_min=5,
        credit_max=75,
        skill_points_formula="EDU*2+MAX(STR,DEX)*2",
        description=(
            "罪犯的体格和相貌形形色色，有些是纯粹碰运气伺机行事，比如扒手和暴徒；有些则组成分"
            "工明确，会详细调查并制定计划的犯罪组织。后者包括银行劫匪、飞贼、赝造者和诈骗者。"
            " 罪犯可能为别人工作，后者通常是“匪帮”或罪犯家族；也可能单打独斗，如果成功的报"
            "酬值得去费力冒险，才会和别人搭伙。自由犯罪者则往往被称为抢劫犯、响马贼和江洋大盗"
            "。"
        ),
        skill_ids=["drive-auto", "heavy-machinery", "intimidate", "lock-smith"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["electrical-repair", "mechanical-repair"],
                label="电气维修或机械维修",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "fighting-brawl",
                    "fighting-sword",
                    "fighting-axe",
                    "fighting-spear",
                    "fighting-whip",
                    "fighting-chain",
                    "fighting-knife",
                ],
                label="格斗（任选一种专精）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "firearm-handgun",
                    "firearm-rifle",
                    "firearm-smg",
                    "firearm-machine-gun",
                    "firearm-bow",
                    "firearm-flamethrower",
                ],
                label="射击（任选一种专精）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=None,
                label="任意一项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=29,
        name="罪犯-打手、暴徒",
        credit_min=5,
        credit_max=30,
        skill_points_formula="EDU*2+STR*2",
        description=(
            "打手、暴徒都是犯罪组织的兵卒。他们被犯罪组织豢养，不过团伙上层出事的时候，倒霉的"
            "往往是他们这些喽啰。对于他们来说，嘴紧和忠心属于职业道德。"
        ),
        skill_ids=["drive-auto", "psychology", "spot-hidden", "stealth"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "fighting-brawl",
                    "fighting-sword",
                    "fighting-axe",
                    "fighting-spear",
                    "fighting-whip",
                    "fighting-chain",
                    "fighting-knife",
                ],
                label="格斗（任选一种专精）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "firearm-handgun",
                    "firearm-rifle",
                    "firearm-smg",
                    "firearm-machine-gun",
                    "firearm-bow",
                    "firearm-flamethrower",
                ],
                label="射击（任选一种专精）",
            ),
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="两项社交技能（取悦、话术、恐吓、说服）",
            ),
        ],
    ),
    OccupationSpec(
        id=30,
        name="罪犯-窃贼",
        credit_min=5,
        credit_max=40,
        skill_points_formula="EDU*2+DEX*2",
        description=(
            "罪犯的体格和相貌形形色色，有些是纯粹碰运气伺机行事，比如扒手和暴徒；有些则组成分"
            "工明确，会详细调查并制定计划的犯罪组织。后者包括银行劫匪、飞贼、赝造者和诈骗者。"
            " 罪犯可能为别人工作，后者通常是“匪帮”或罪犯家族；也可能单打独斗，如果成功的报"
            "酬值得去费力冒险，才会和别人搭伙。自由犯罪者则往往被称为抢劫犯、响马贼和江洋大盗"
            "。"
        ),
        skill_ids=[
            "appraise",
            "climb",
            "listen",
            "lock-smith",
            "sleight-of-hand",
            "spot-hidden",
            "stealth",
        ],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["electrical-repair", "mechanical-repair"],
                label="电气维修或机械维修",
            ),
        ],
    ),
    OccupationSpec(
        id=31,
        name="罪犯-欺诈师",
        credit_min=10,
        credit_max=65,
        skill_points_formula="EDU*2+APP*2",
        description=(
            "欺诈师通常都是油嘴滑舌的人物。他们或单独或集体出没在富裕的人家和小区周边，诈取他"
            "们来之不易的钱财。许多骗局覆杂精妙，诈骗团伙会倾巢出动乃至租用建筑；有些则不需要"
            "这么麻烦，只要一个骗子几分钟就能搞定。"
        ),
        skill_ids=["appraise", "listen", "psychology", "sleight-of-hand"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["art-craft-1", "art-craft-2", "art-craft-3"],
                label="技艺（表演）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "language-foreign-1",
                    "language-foreign-2",
                    "language-foreign-3",
                ],
                label="法律或外语",
            ),
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="两项社交技能（取悦、话术、恐吓、说服）",
            ),
        ],
    ),
    OccupationSpec(
        id=32,
        name="罪犯-独行罪犯",
        credit_min=5,
        credit_max=65,
        skill_points_formula="EDU*2+MAX(DEX,APP)*2",
        description=(
            "罪犯的体格和相貌形形色色，有些是纯粹碰运气伺机行事，比如扒手和暴徒；有些则组成分"
            "工明确，会详细调查并制定计划的犯罪组织。后者包括银行劫匪、飞贼、赝造者和诈骗者。"
            " 罪犯可能为别人工作，后者通常是“匪帮”或罪犯家族；也可能单打独斗，如果成功的报"
            "酬值得去费力冒险，才会和别人搭伙。自由犯罪者则往往被称为抢劫犯、响马贼和江洋大盗"
            "。"
        ),
        skill_ids=["appraise", "psychology", "spot-hidden", "stealth"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["art-craft-1", "art-craft-2", "art-craft-3"],
                label="技艺（表演）或乔装",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "fighting-brawl",
                    "fighting-sword",
                    "fighting-axe",
                    "fighting-spear",
                    "fighting-whip",
                    "fighting-chain",
                    "fighting-knife",
                    "firearm-handgun",
                    "firearm-rifle",
                    "firearm-smg",
                    "firearm-machine-gun",
                    "firearm-bow",
                    "firearm-flamethrower",
                ],
                label="格斗或射击（任选一种专精）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="一项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["lock-smith", "mechanical-repair"],
                label="锁匠或机械维修",
            ),
        ],
    ),
    OccupationSpec(
        id=33,
        name="罪犯-女飞贼（古典）",
        credit_min=10,
        credit_max=80,
        skill_points_formula="EDU*2+APP*2",
        description=(
            "女飞贼是名为专业大盗的女人。大部分都是独立行动，也有对自己的男伴言听计从的时候。"
            " 不过这也不一定，实际上情况可能完全相反，她完全可以在干了某一票以后就卷走所有现"
            "金和皮草溜之大吉。"
        ),
        skill_ids=["drive-auto", "listen", "stealth"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["art-craft-1", "art-craft-2", "art-craft-3"],
                label="技艺（任意）",
            ),
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="两项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["fighting-brawl", "firearm-handgun"],
                label="格斗（斗殴）或射击（手枪）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=None,
                label="任意一项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=34,
        name="罪犯-赃物贩子",
        credit_min=20,
        credit_max=40,
        skill_points_formula="EDU*2+APP*2",
        description=(
            "赃物贩子，顾名思义是买卖偷抢来的财产，通常是收购赃物并转手卖给其他罪犯或(无意中"
            ")守法的顾客。主要来说，他们是小偷和买家的中间人，有时也会从交易中收取提成；不过"
            "更常见的还是以极低的价格直接收购赃物。"
        ),
        skill_ids=["accounting", "appraise", "history", "library-use", "spot-hidden"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="一项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=None,
                label="任意一项其他技能",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["art-craft-1", "art-craft-2", "art-craft-3"],
                label="技艺（任一）",
            ),
        ],
    ),
    OccupationSpec(
        id=35,
        name="罪犯-赝造者",
        credit_min=20,
        credit_max=60,
        skill_points_formula="EDU*4",
        description=(
            "赝造者是地下世界的艺术家，专门从事伪造官方文件、契约、转让书，并提供伪造的签名。"
            "初学者只能做做小贼的假身份证，而顶级的赝造者连印假币的铸模都能做。"
        ),
        skill_ids=[
            "accounting",
            "appraise",
            "history",
            "library-use",
            "sleight-of-hand",
            "spot-hidden",
        ],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["art-craft-1", "art-craft-2", "art-craft-3"],
                label="技艺（伪造）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=None,
                label="任意一项其他个人或时代特长（如计算机）",
            ),
        ],
    ),
    OccupationSpec(
        id=36,
        name="罪犯-走私者",
        credit_min=20,
        credit_max=60,
        skill_points_formula="EDU*2+MAX(APP,DEX)*2",
        description=(
            "走私一直是一个有利可图的高风险行当。走私者往往有一个合法的表面职业，比如船长、飞"
            "行员或商人，以掩盖他们非法运输的行为。"
        ),
        skill_ids=["listen", "navigation", "psychology", "sleight-of-hand", "spot-hidden"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "firearm-handgun",
                    "firearm-rifle",
                    "firearm-smg",
                    "firearm-machine-gun",
                    "firearm-bow",
                    "firearm-flamethrower",
                ],
                label="射击（任一）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="一项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["drive-auto", "pilot-aircraft", "pilot-boat"],
                label="汽车驾驶或驾驶（飞行器或船）",
            ),
        ],
    ),
    OccupationSpec(
        id=37,
        name="罪犯-混混",
        credit_min=3,
        credit_max=10,
        skill_points_formula="EDU*2+MAX(STR,DEX)*2",
        description=(
            "街头混混一般都是些小年轻，弄不好还在寻觅加入真正黑帮的契机。不过他们的本事也就限"
            "于偷车，盗窃商店货物，抢钱或者夜盗。"
        ),
        skill_ids=["climb", "jump", "sleight-of-hand", "stealth", "throw"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="一项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "fighting-brawl",
                    "fighting-sword",
                    "fighting-axe",
                    "fighting-spear",
                    "fighting-whip",
                    "fighting-chain",
                    "fighting-knife",
                ],
                label="格斗（任一）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "firearm-handgun",
                    "firearm-rifle",
                    "firearm-smg",
                    "firearm-machine-gun",
                    "firearm-bow",
                    "firearm-flamethrower",
                ],
                label="射击（任一）",
            ),
        ],
    ),
    OccupationSpec(
        id=38,
        name="教团首领",
        credit_min=30,
        credit_max=60,
        skill_points_formula="EDU*4",
        description=(
            "美国的新兴宗教层出不穷。直到现在，也还有从新英格兰超验主义到“天父的儿女”等等许"
            "多种类。教团首领有的创立了严格的教条并且对信徒推行，另一些则仅仅是垂涎于信徒的金"
            "钱和权势。 在1920 年代，各种诱惑性的新兴宗教团体纷纷涌现。有些采取基督教的"
            "形式，有些则混杂了东方的神秘主义和神秘学的仪式。美国西海岸的人对这些教团屡见不鲜"
            "，不过其他形式的教团全国各地都存在。在美国南部的“圣经带”，就有许多巡回帐篷演出"
            "圣歌、舞蹈，推行信仰覆兴。其他国家也是一样，只要有需要信仰的人，就会有新兴宗教团"
            "体。"
        ),
        skill_ids=["accounting", "occult", "psychology", "spot-hidden"],
        choice_slots=[
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="两项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=None,
                label="任意其他两项其他个人特长",
            ),
        ],
    ),
    OccupationSpec(
        id=39,
        name="除魅师（现代）",
        credit_min=20,
        credit_max=50,
        skill_points_formula="EDU*4",
        description=(
            "除魅师的工作是说服(或者强迫)一个人放弃自己的信仰或是对宗教团体、社会团体的忠心"
            "。他们一般受雇于深陷教团之类组织的人的亲属，任务就是解救对方(通常靠绑架)，并通"
            "过心理学手段使他们割断与原来教团的联系(“控制”)。 也有不那么激烈的除魅师，他"
            "们的工作对象则是那些自愿离开教团的人，为他们完全地退出教团进行有效的指导。"
        ),
        skill_ids=["drive-auto", "history", "occult", "psychology", "stealth"],
        choice_slots=[
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="两项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "fighting-brawl",
                    "firearm-handgun",
                    "firearm-rifle",
                    "firearm-smg",
                    "firearm-machine-gun",
                    "firearm-bow",
                    "firearm-flamethrower",
                ],
                label="格斗（斗殴）或射击（任一）",
            ),
        ],
    ),
    OccupationSpec(
        id=40,
        name="设计师",
        credit_min=20,
        credit_max=60,
        skill_points_formula="EDU*4",
        description=(
            "设计师的工作包括许多方面，从时装到家具或是其他任何东西。他们自由工作，为设计工作"
            "室和企业设计产品、流程、法律、游戏、图像等等。 调查员特定的设计方向也会影响他们"
            "对专业技能的选择，如果需要的话要进行调整。"
        ),
        skill_ids=["accounting", "mechanical-repair", "photography", "psychology", "spot-hidden"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["art-craft-1", "art-craft-2", "art-craft-3"],
                label="技艺（任一）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["computer-use", "library-use"],
                label="计算机或图书馆",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=None,
                label="任意一项其他个人特长",
            ),
        ],
    ),
    OccupationSpec(
        id=41,
        name="业余艺术爱好者（原作向）",
        credit_min=50,
        credit_max=99,
        skill_points_formula="EDU*2+APP*2",
        description=(
            "业余艺术爱好者靠经济自立、遗产继承、信托基金或者其他各种来源保障自己的生活开支，"
            "没有必要自己工作。如果经济条件足够好，他们甚至可以雇佣专业的经济顾问来打理自己的"
            "产业。他们可能有很高的学历，但不一定是真才实学；优越的经济条件使得他们性情古怪，"
            "口无遮拦。 在1920 年代，这些人可能会被时人称为“摩登女郎”或者“公子哥儿”"
            "，当然想当一个社交“名流”其实并不要求他有多有钱。换作现代，“时髦”则是恰如其分"
            "的形容词。 业余艺术爱好者有着大把的时间考虑如何变得潇洒世故，不过花这些时间去做"
            "别的事可是违背他们的天性和兴致。"
        ),
        skill_ids=["ride"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["art-craft-1", "art-craft-2", "art-craft-3"],
                label="技艺（任一）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "firearm-handgun",
                    "firearm-rifle",
                    "firearm-smg",
                    "firearm-machine-gun",
                    "firearm-bow",
                    "firearm-flamethrower",
                ],
                label="射击（任选一项专精）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "language-foreign-1",
                    "language-foreign-2",
                    "language-foreign-3",
                ],
                label="外语（任一）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="一项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=3,
                candidate_skill_ids=None,
                label="任意三项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=42,
        name="潜水员",
        credit_min=9,
        credit_max=30,
        skill_points_formula="EDU*2+DEX*2",
        description=(
            "潜水员可能在军队、执法机构或海绵采集、海上救援、环境保护甚至水下寻宝的民间机构工作。"
        ),
        skill_ids=[
            "diving",
            "first-aid",
            "mechanical-repair",
            "pilot-boat",
            "science-biology",
            "spot-hidden",
            "swim",
        ],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=None,
                label="任意一项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=43,
        name="医生（原作向）",
        credit_min=30,
        credit_max=80,
        skill_points_formula="EDU*4",
        description=(
            "医生这里可能是指全科医生、外科医生、其他专科医生或者独立医学研究员。除去个人的目"
            "标以外，救死扶伤、获得财富和荣誉、提升公众的理性意识和科学素养也常常是医生的理想"
            "。 农村和小城镇的卫生院是全科医生的舞台，而大城市的各大医院则是高手如云，集聚了"
            "众多专攻病理学、毒理学、整形外科、脑外科等领域的专家。有些医生也可能担任全职或兼"
            "职的法医，进行尸检，并为市、县、州级执法机构出具检验报告。 在美国，行医资格由各"
            "州认证，大多要求最少两年的正规医学院校学习经历。不过这个规定还是比较晚近的，在1"
            "920 年代很多年长的医生尽管没受过任何正规专业教育，仍然可以获得医师执照。"
        ),
        skill_ids=["first-aid", "medicine", "psychology", "science-biology", "science-pharmacy"],
        choice_slots=[
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=None,
                label="任两种其他学术或个人特长",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "language-foreign-1",
                    "language-foreign-2",
                    "language-foreign-3",
                ],
                label="外语（任一）",
            ),
        ],
    ),
    OccupationSpec(
        id=44,
        name="流浪者",
        credit_min=0,
        credit_max=5,
        skill_points_formula="EDU*2+MAX(APP,DEX,STR)*2",
        description=(
            "相对于那些因贫困而苦恼的人，流浪者选择四处漂泊的生活，可能是出于社会、哲学、经济"
            "的原因，或只是渴望摆脱社会的约束。 流浪汉需要工作，有时几天或几个月，但他们应对"
            "问题时往往选择流动和孤立，而不是舒适和亲近。在美国，这种情况尤其常见，只要旅行本"
            "身没有什么危险，就会有人选择漂泊为生。"
        ),
        skill_ids=["climb", "jump", "listen", "navigation", "stealth"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="一项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=None,
                label="任意两项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=45,
        name="司机-私人司机",
        credit_min=10,
        credit_max=40,
        skill_points_formula="EDU*2+DEX*2",
        description="私人司机是直接受雇于个人或企业，或者是专门提供连人带车的私人司机业务的中介机构。",
        skill_ids=["drive-auto", "listen", "mechanical-repair", "navigation", "spot-hidden"],
        choice_slots=[
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="两项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=None,
                label="任意一项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=46,
        name="司机-司机",
        credit_min=9,
        credit_max=20,
        skill_points_formula="EDU*2+MAX(STR,DEX)*2",
        description=(
            "专职司机可能为企业、个人工作，也可能拥有自己的出租车或货车。通常司机还要通过警方"
            "的背景调查，获得特殊的驾驶许可证。"
        ),
        skill_ids=[
            "accounting",
            "drive-auto",
            "listen",
            "mechanical-repair",
            "navigation",
            "psychology",
        ],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="一项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=None,
                label="任意一项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=47,
        name="司机-出租车司机",
        credit_min=9,
        credit_max=30,
        skill_points_formula="EDU*2+DEX*2",
        description=(
            "出租车司机可能属于大大小小的出租车公司，也可能靠自己的车和证件运营(在美国，需要"
            "出租车牌照)。出租车公司负责为出租车司机登记车辆并分配调度，方便司机自由揽客。出"
            "租车上必须统一安装计价器，并由出租车协会进行定期检查。"
        ),
        skill_ids=[
            "accounting",
            "drive-auto",
            "electrical-repair",
            "fast-talk",
            "mechanical-repair",
            "navigation",
            "spot-hidden",
        ],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=None,
                label="任意一项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=48,
        name="编辑",
        credit_min=10,
        credit_max=30,
        skill_points_formula="EDU*4",
        description=(
            "编辑的工作包括审核记者的稿件，撰写报刊社论，应对各种突发事件、到了截稿时间要催稿"
            "，编辑工作只好偶尔为之啦。大型报社的编辑数量众多，包括比起新闻编辑更多参与业务运"
            "营的主编。其他编辑专门负责时尚、体育或者其他板块。许多小报可能就只有一个编辑，他"
            "甚至有可能就是报社的业主或者唯一的全职员工。"
        ),
        skill_ids=["accounting", "history", "language-native", "psychology", "spot-hidden"],
        choice_slots=[
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="两项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=None,
                label="任意一项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=49,
        name="政府官员",
        credit_min=50,
        credit_max=90,
        skill_points_formula="EDU*2+APP*2",
        description=(
            "以民选方式选举出来的政府官员享有与他们的职位相符的声望。小城市的市长和城镇的镇长"
            "之类，他们的影响力基本出不了城镇的范围，而且这样的职务基本上是兼职的，报酬也很少"
            "。大城市的市长，工资就相当可观了，而且还能把自己的城市管理得像小王国一样，影响力"
            "和权力比所在州的州长还要大。 州议会的众参两院议员是相当有面子的职位，尤其是在商"
            "界和本州岛的其他业界。 州长负责全州的事务，是联系各州和国家的纽带。 联邦政府拥"
            "有最高等级的影响力。众议院议员由各州按本州岛人口所占比重选派的共400 余名议员"
            "组成，任期为两年。参议院则是不论各州大小，每州选派两名议员到花生屯任职。任期长达"
            "六年，人数不超过一百，所以参议员更是权倾一方，许多年长的议员能够享受总统级的待遇"
            "。 在英国，下议院议员由选举产生，任期四到五年；上议院议员则不由选举产生，是世袭"
            "制或由君主指任。"
        ),
        skill_ids=[
            "charm",
            "fast-talk",
            "history",
            "intimidate",
            "language-native",
            "listen",
            "persuade",
            "psychology",
        ],
    ),
    OccupationSpec(
        id=50,
        name="工程师",
        credit_min=30,
        credit_max=60,
        skill_points_formula="EDU*4",
        description=(
            "工程师精通机械和电气设备，可能在民间或军工企业工作，也可能是个发明家。他们擅长应"
            "用科学、数学知识和丰富的创造思维，解决各种技术问题。"
        ),
        skill_ids=[
            "electrical-repair",
            "heavy-machinery",
            "library-use",
            "mechanical-repair",
            "science-engineering",
            "science-physics",
        ],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=None,
                label="任意一项其他个人或时代特长",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["art-craft-1", "art-craft-2", "art-craft-3"],
                label="技艺（任一）",
            ),
        ],
    ),
    OccupationSpec(
        id=51,
        name="艺人",
        credit_min=9,
        credit_max=70,
        skill_points_formula="EDU*2+APP*2",
        description=(
            "艺人包括小丑、歌手、舞蹈演员、喜剧演员、杂耍艺人、魔术师，各种以在人前表演谋生的"
            "人。他们乐于向更多的人表现自己的能力，并期待观众回报的掌声。 在1920 年代，"
            "这一职业并不受人尊重。不过1920 年代好莱坞明星的高薪彻底改变了很多人的想法，"
            "现在这个职业背景已经通常被视作是优势了。"
        ),
        skill_ids=["disguise", "listen", "psychology"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["art-craft-1", "art-craft-2", "art-craft-3"],
                label="技艺（表演类，如表演、演唱、喜剧等）",
            ),
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="两项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=None,
                label="任意两项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=52,
        name="探险家（古典）",
        credit_min=55,
        credit_max=80,
        skill_points_formula="EDU*2+MAX(APP,DEX,STR)*2",
        description=(
            "在20 世纪早期，这世界还有许多地区尚未有人涉足，而探索这些地方正是探险家的工作"
            "。这种令人兴奋不已的生活方式，其经济来源则是科学界的赞助、私人的捐赠、博物馆的委"
            "托和报纸杂志图书电影的版权等等。 黑非洲的大部分仍然不为人知，同样的地方还包括了"
            "南美的马托格罗索高原，澳大利亚的大沙沙漠，撒哈拉和阿拉伯沙漠，和亚洲的茫茫戈壁。"
            "尽管南北极点已经被探险家征服了，但周围很大部分的地区仍然是未知的。"
        ),
        skill_ids=["history", "jump", "natural-world", "navigation", "survival"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["climb", "swim"],
                label="攀爬或游泳",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "firearm-handgun",
                    "firearm-rifle",
                    "firearm-smg",
                    "firearm-machine-gun",
                    "firearm-bow",
                    "firearm-flamethrower",
                ],
                label="射击（任选一项专精）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "language-foreign-1",
                    "language-foreign-2",
                    "language-foreign-3",
                ],
                label="外语（任一）",
            ),
        ],
    ),
    OccupationSpec(
        id=53,
        name="农民",
        credit_min=9,
        credit_max=30,
        skill_points_formula="EDU*2+MAX(STR,DEX)*2",
        description=(
            "农民可能自己拥有土地，自己从事农牧业，也可能是受雇在农场工作。农业劳动繁重而枯燥"
            "，特别适合那些喜欢户外体力劳动的人。 1920 年代是美国城镇人口超过农村人口的"
            "首个十年。从这时起一直到现在，自耕农民都在受到规模化农业企业和剧烈波动的农产品市"
            "场的双重冲击。"
        ),
        skill_ids=["heavy-machinery", "mechanical-repair", "natural-world", "track"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["drive-auto", "drive-carriage"],
                label="汽车驾驶（或运货马车）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="一项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=None,
                label="任意一项其他个人或时代特长",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["art-craft-1", "art-craft-2", "art-craft-3"],
                label="技艺（任一）",
            ),
        ],
    ),
    OccupationSpec(
        id=54,
        name="联邦探员",
        credit_min=20,
        credit_max=40,
        skill_points_formula="EDU*4",
        description=(
            "联邦执法机构和特工种类各异。有些身着制服，比如美国司法部的人员；另外一些则穿便服"
            "，工作内容也类似警探，比如联邦调查局的人员。"
        ),
        skill_ids=["drive-auto", "fighting-brawl", "law", "persuade", "spot-hidden", "stealth"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "firearm-handgun",
                    "firearm-rifle",
                    "firearm-smg",
                    "firearm-machine-gun",
                    "firearm-bow",
                    "firearm-flamethrower",
                ],
                label="射击（任选一项专精）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=None,
                label="任意一项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=55,
        name="消防员",
        credit_min=9,
        credit_max=30,
        skill_points_formula="EDU*2+MAX(STR,DEX)*2",
        description=(
            "消防员是公职人员，通常为所管辖的小区服务。他们夜以继日地工作，或者连续几天的倒班"
            "工作，吃住包括娱乐活动都要局限在消防局里。消防员的管理结构类似军队，职位包括中尉"
            "、上尉和局长等等。"
        ),
        skill_ids=[
            "climb",
            "dodge",
            "drive-auto",
            "first-aid",
            "heavy-machinery",
            "jump",
            "mechanical-repair",
            "throw",
        ],
    ),
    OccupationSpec(
        id=56,
        name="驻外记者",
        credit_min=10,
        credit_max=40,
        skill_points_formula="EDU*4",
        description=(
            "驻外记者是新闻界的精英人才。他们拿着固定工资,靠报销单环游全世界。在 1920 "
            "年代,驻外记者通常供职于大型报社、广播电台、或者国家级通讯社。当代的驻外记者也可"
            "能自由撰稿或 者为电视台、网络通讯社和国际新闻通讯社工作。 这个职业的工作内容五"
            "花八门,经常能激动人心。不过博物学灾害、政治动荡和战争也会成为驻外记者报导的主要"
            "内容,工作也不总是一帆风 顺。"
        ),
        skill_ids=["history", "language-native", "listen", "psychology"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "language-foreign-1",
                    "language-foreign-2",
                    "language-foreign-3",
                ],
                label="外语（任一）",
            ),
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="两项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=None,
                label="任意一项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=57,
        name="法医",
        credit_min=40,
        credit_max=60,
        skill_points_formula="EDU*4",
        description=(
            "法医是一个高度专门化的职业,大多数法医为市、县或州执法机构工作。工作内容包括尸体"
            "解剖,推定死因,并为公诉人提供建议。法医也常常会在刑事审判中出庭提供证言。"
        ),
        skill_ids=[
            "library-use",
            "medicine",
            "persuade",
            "science-biology",
            "science-forensics",
            "science-pharmacy",
            "spot-hidden",
        ],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "language-foreign-1",
                    "language-foreign-2",
                    "language-foreign-3",
                ],
                label="外语（任一）",
            ),
        ],
    ),
    OccupationSpec(
        id=58,
        name="赌徒",
        credit_min=8,
        credit_max=50,
        skill_points_formula="EDU*2+MAX(APP,DEX)*2",
        description=(
            "赌徒是罪犯世界里最花哨的一群人。他们衣 着光鲜,不论朴实还是华丽都魅力四射。不论"
            "是靠赛马、纸牌游戏还是其他赌博方式,他们总是要凭自己的运气过活。 老练的赌徒会频"
            "繁地光顾犯罪组织开设的地 下赌场。少数赌场高手可能经常参加漫长而又一掷千金的豪赌"
            ",甚至可能有外部利益集团作为后台。 低级的赌徒则出入于狭窄的小巷,在骰子房 耍弄"
            "灌铅的骰子,或者是挤坐在阴暗的台球室里。"
        ),
        skill_ids=["accounting", "listen", "psychology", "sleight-of-hand", "spot-hidden"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["art-craft-1", "art-craft-2", "art-craft-3"],
                label="技艺（表演）",
            ),
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="两项社交技能（取悦、话术、恐吓、说服）",
            ),
        ],
    ),
    OccupationSpec(
        id=59,
        name="黑帮-黑帮老大",
        credit_min=60,
        credit_max=95,
        skill_points_formula="EDU*2+APP*2",
        description=(
            "黑帮可能是整个城市、一部分城市的大佬, 也可能只是给这些大佬打工的马仔。马仔们通"
            "常 有自己的保护范围,比如监管非法运输和收取保 护费等等。老板总管业务,负责交易"
            ",并要就各 种各样的问题给马仔们拿主意。更重要的是,老 板可以各种高人一等,只要"
            "能找到马仔或者小弟 去干的事,他基本是不肯污了自己的手去做的。 黑社会在 192"
            "0 年代上升为突出的社会问题。本来仅限于在本地收收保护费和管管赌场的外国 裔黑帮"
            ",不约而同地发现了贩卖私酒带来的巨大 利润。没过多久,他们就掌控了城市的大片区域"
            ", 并在街上和其他黑帮火并。虽然大部分黑帮是按 来源的民族划分——如爱尔兰裔、意"
            "大利裔、非 洲裔和犹太裔,黑帮的成员仍然可能是任何民族。 如今,贩毒则取代其他,"
            "成为多数黑帮中来 钱最快的犯罪门路。和 1920 年代前辈的工作方法 类似,现在"
            "的黑帮老大也需要大量的小弟来负责 保卫、推广、在街道里推行自己的业务。 除去贩私"
            "酒和贩毒以外,卖淫、保护、赌博、 腐败等等都是这些犯罪组织的业务范围。"
        ),
        skill_ids=["law", "listen", "psychology", "spot-hidden"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "fighting-brawl",
                    "fighting-sword",
                    "fighting-axe",
                    "fighting-spear",
                    "fighting-whip",
                    "fighting-chain",
                    "fighting-knife",
                ],
                label="格斗（任选一项专精）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "firearm-handgun",
                    "firearm-rifle",
                    "firearm-smg",
                    "firearm-machine-gun",
                    "firearm-bow",
                    "firearm-flamethrower",
                ],
                label="射击（任选一项专精）",
            ),
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="两项社交技能（取悦、话术、恐吓、说服）",
            ),
        ],
    ),
    OccupationSpec(
        id=60,
        name="黑帮-马仔",
        credit_min=9,
        credit_max=20,
        skill_points_formula="EDU*2+MAX(STR,DEX)*2",
        description=(
            "黑帮可能是整个城市、一部分城市的大佬, 也可能只是给这些大佬打工的马仔。马仔们通"
            "常 有自己的保护范围,比如监管非法运输和收取保 护费等等。老板总管业务,负责交易"
            ",并要就各 种各样的问题给马仔们拿主意。更重要的是,老 板可以各种高人一等,只要"
            "能找到马仔或者小弟 去干的事,他基本是不肯污了自己的手去做的。 黑社会在 192"
            "0 年代上升为突出的社会问题。本来仅限于在本地收收保护费和管管赌场的外国 裔黑帮"
            ",不约而同地发现了贩卖私酒带来的巨大 利润。没过多久,他们就掌控了城市的大片区域"
            ", 并在街上和其他黑帮火并。虽然大部分黑帮是按 来源的民族划分——如爱尔兰裔、意"
            "大利裔、非 洲裔和犹太裔,黑帮的成员仍然可能是任何民族。 如今,贩毒则取代其他,"
            "成为多数黑帮中来 钱最快的犯罪门路。和 1920 年代前辈的工作方法 类似,现在"
            "的黑帮老大也需要大量的小弟来负责 保卫、推广、在街道里推行自己的业务。 除去贩私"
            "酒和贩毒以外,卖淫、保护、赌博、 腐败等等都是这些犯罪组织的业务范围。"
        ),
        skill_ids=["drive-auto", "psychology"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "fighting-brawl",
                    "fighting-sword",
                    "fighting-axe",
                    "fighting-spear",
                    "fighting-whip",
                    "fighting-chain",
                    "fighting-knife",
                ],
                label="格斗（任选一项专精）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "firearm-handgun",
                    "firearm-rifle",
                    "firearm-smg",
                    "firearm-machine-gun",
                    "firearm-bow",
                    "firearm-flamethrower",
                ],
                label="射击（任选一项专精）",
            ),
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="两项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=None,
                label="任意两项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=61,
        name="绅士、淑女",
        credit_min=40,
        credit_max=90,
        skill_points_formula="EDU*2+APP*2",
        description=(
            "绅士淑女指的是有良好的教养品行、举止彬彬有礼的人。通常用来称呼上流社会(通过继承"
            " 或津贴)拥有相当财富的人。 在上世纪 20 年代,这样的人至少要有一个仆 人("
            "管家、男仆、女仆、私人司机),还要有城 市或乡村的宅第。家庭的富有并不重要,因为"
            "家庭的社会地位往往比财产更被上流社会所看重。"
        ),
        skill_ids=["firearm-rifle", "history", "navigation", "ride"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["art-craft-1", "art-craft-2", "art-craft-3"],
                label="技艺（任一）",
            ),
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="两项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "language-foreign-1",
                    "language-foreign-2",
                    "language-foreign-3",
                ],
                label="外语（任一）",
            ),
        ],
    ),
    OccupationSpec(
        id=62,
        name="游民",
        credit_min=0,
        credit_max=5,
        skill_points_formula="EDU*2+MAX(APP,DEX)*2",
        description=(
            "游民只有少数的人愿意去当,虽然失业的人、 醉倒在阴沟里的醉鬼到处都是。和流浪者只"
            "会在 必需时才工作不同,游民的工作本身就是流浪。 他们不断地坐火车旅行,从一个城"
            "市辗转到 另一个城市,他们是身无分文的诗人、漂泊者, 铁路上的探索者、冒险者和盗"
            "贼。但是铁路上的生活一样充满危险。且不说穷困潦倒、无家可归, 还要面对来自警察、"
            "周围居民和铁路员工的敌意。另外在深夜中跳车并不是一件容易的事,在跳车的时候被车厢"
            "夹断过手脚的人可是不可胜数。"
        ),
        skill_ids=["climb", "jump", "listen", "navigation", "stealth"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["art-craft-1", "art-craft-2", "art-craft-3"],
                label="技艺（任一）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["lock-smith", "sleight-of-hand"],
                label="锁匠或妙手",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=None,
                label="任意一项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=63,
        name="勤杂护工",
        credit_min=6,
        credit_max=15,
        skill_points_formula="EDU*2+STR*2",
        description=(
            "勤杂护工在医院的工作包括倒垃圾、打扫房间、运送病人,还有一些其他乱七八糟的工作。"
            "总之对他们的要求不比对看门人多多少。"
        ),
        skill_ids=[
            "electrical-repair",
            "fighting-brawl",
            "first-aid",
            "listen",
            "mechanical-repair",
            "psychology",
            "stealth",
        ],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="一项社交技能（取悦、话术、恐吓、说服）",
            ),
        ],
    ),
    OccupationSpec(
        id=64,
        name="记者(原作向)-调查记者",
        credit_min=9,
        credit_max=30,
        skill_points_formula="EDU*4",
        description=(
            "记者用文字对当天的新闻事件进行报导与评 论,一天之内就要完成一个作家一周的工作量"
            "。他们通常为报纸、杂志、广播电台、电视台或者新闻网站撰稿。 优秀的调查记者在报导"
            "事件的同时,即使面对丑恶,也能保持自身的清廉正直。恶心的记者则被现实所压倒,最终"
            "丧失自己的节操,肆意操纵文字歪曲真相。"
        ),
        skill_ids=["history", "language-native", "library-use", "psychology"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["art-craft-1", "art-craft-2", "art-craft-3"],
                label="技艺（艺术或摄影）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="一项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=None,
                label="任意两项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=65,
        name="记者(原作向)-通讯记者",
        credit_min=9,
        credit_max=30,
        skill_points_formula="EDU*4",
        description=(
            "通讯记者则是新闻传媒行业大军中的一员, 不管是自由撰稿或是在报社、杂志社、新闻网"
            "站、 通讯社工作。大部分记者从事实地工作,包括走 访见证人、查看记录、收集叙述。"
            "有些记者被安 排专门追踪警界、体育界或商界的热点新闻,其他人则是负责社会事件乃至"
            "园艺俱乐部之类的事情。 通讯记者都会携带记者证,不过记者证除了 各通讯社(主要是"
            "报社)用来识别自己的雇员以 外没有太大的作用。实际上记者的工作内容更像 私家侦探"
            ",有时为了获得第一手消息也难免使点嘴上花招。"
        ),
        skill_ids=["history", "language-native", "listen", "psychology", "spot-hidden", "stealth"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="一项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["art-craft-1", "art-craft-2", "art-craft-3"],
                label="技艺（任一）",
            ),
        ],
    ),
    OccupationSpec(
        id=66,
        name="法官",
        credit_min=50,
        credit_max=80,
        skill_points_formula="EDU*4",
        description=(
            "法官是主持审判全过程的人,可能单独工作或是和同事组成合议庭。一般是推选或任命制,"
            " 工作年限也分定期和终身。有的人是初出茅庐就当了法官,而其余的绝大多数,不论是在"
            "联邦最高法院还是遥远西部小镇的法官,其实至少都是经过注册的律师。"
        ),
        skill_ids=[
            "history",
            "intimidate",
            "language-native",
            "law",
            "library-use",
            "listen",
            "persuade",
            "psychology",
        ],
    ),
    OccupationSpec(
        id=67,
        name="实验室助理",
        credit_min=10,
        credit_max=30,
        skill_points_formula="EDU*4",
        description=(
            "实验室助理在科研环境中工作,在首席科学家的监督下进行实验和行政工作。 研究内容可"
            "能依首席科学家的研究学科而变 化。但基本都包括取样、测试、记录和分析数据、 调整"
            "和进行实验、制备标本和样品、管理实验室的日常工作,和保护工作人员的健康与安全。"
        ),
        skill_ids=["electrical-repair", "science-chemistry", "spot-hidden"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["computer-use", "library-use"],
                label="计算机或图书馆（二选一）",
            ),
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=[
                    "science-pharmacy",
                    "science-biology",
                    "science-physics",
                    "science-geology",
                    "science-astronomy",
                    "science-forensics",
                    "science-mathematics",
                    "science-engineering",
                    "science-botany",
                    "science-zoology",
                    "science-cryptography",
                    "science-metallurgy",
                    "science-meteorology",
                ],
                label="科学（化学之外任意两项）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=None,
                label="任意一项其他个人特长",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "language-foreign-1",
                    "language-foreign-2",
                    "language-foreign-3",
                ],
                label="外语（任一）",
            ),
        ],
    ),
    OccupationSpec(
        id=68,
        name="工人-非熟练工人",
        credit_min=9,
        credit_max=30,
        skill_points_formula="EDU*2+MAX(STR,DEX)*2",
        description=(
            "工人这一大类职业包括工厂工人、纺织工人、 码头工人、养路工人、矿工、建筑工人等等"
            "。工人分为两种类型:熟练工和非熟练工。普通的工人虽然技术不熟练,但是仍然长于使用"
            "电动工具、 起重机和其他工厂设备。"
        ),
        skill_ids=[
            "drive-auto",
            "electrical-repair",
            "first-aid",
            "heavy-machinery",
            "mechanical-repair",
            "throw",
        ],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "fighting-brawl",
                    "fighting-sword",
                    "fighting-axe",
                    "fighting-spear",
                    "fighting-whip",
                    "fighting-chain",
                    "fighting-knife",
                ],
                label="格斗（任选一项专精）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=None,
                label="任意一项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=69,
        name="工人-伐木工",
        credit_min=9,
        credit_max=30,
        skill_points_formula="EDU*2+MAX(STR,DEX)*2",
        description=(
            "工人这一大类职业包括工厂工人、纺织工人、 码头工人、养路工人、矿工、建筑工人等等"
            "。工人分为两种类型:熟练工和非熟练工。普通的工人虽然技术不熟练,但是仍然长于使用"
            "电动工具、 起重机和其他工厂设备。"
        ),
        skill_ids=[
            "climb",
            "dodge",
            "fighting-chainsaw",
            "first-aid",
            "jump",
            "mechanical-repair",
            "throw",
        ],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["natural-world", "science-biology", "science-botany"],
                label="自然或科学（生物学或植物学）",
            ),
        ],
    ),
    OccupationSpec(
        id=70,
        name="工人-矿工",
        credit_min=9,
        credit_max=30,
        skill_points_formula="EDU*2+MAX(STR,DEX)*2",
        description=(
            "工人这一大类职业包括工厂工人、纺织工人、 码头工人、养路工人、矿工、建筑工人等等"
            "。工人分为两种类型:熟练工和非熟练工。普通的工人虽然技术不熟练,但是仍然长于使用"
            "电动工具、 起重机和其他工厂设备。"
        ),
        skill_ids=[
            "climb",
            "heavy-machinery",
            "jump",
            "mechanical-repair",
            "science-geology",
            "spot-hidden",
            "stealth",
        ],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=None,
                label="任意一项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=71,
        name="律师",
        credit_min=30,
        credit_max=80,
        skill_points_formula="EDU*4",
        description=(
            "律师或法律顾问精通他们所在地区的法律，擅长把抽象的法学理论知识联系起来，为客户解"
            "决法律方面的疑难，担任辩护代理、法律顾问的工作，为客户提供解决办法。可能受托处理"
            "个人案件、接受法院指定，也可能专门为某个富裕客户或公司服务。 在美国，“律师”一"
            "词一般只指辩护律师。在英国，“律师”一词则包括高级律师、初级律师还有一些执法机构"
            "。 假如碰上好客户的话，律师自己也可以一战成名，少数律师还能以自己在政治经济方面"
            "的获益吸引媒体的关注。"
        ),
        skill_ids=["accounting", "law", "library-use", "psychology"],
        choice_slots=[
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="两项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=None,
                label="两项其他技能",
            ),
        ],
    ),
    OccupationSpec(
        id=72,
        name="图书馆管理员（原作向）",
        credit_min=9,
        credit_max=35,
        skill_points_formula="EDU*4",
        description=(
            "图书馆管理员在公共机构和图书馆工作，负责管理图书目录和书库，并处理图书借阅等。在"
            "现代，图书馆管理员还要负责管理视听数据、电子书库。 一些大公司可能聘用图书馆管理"
            "员管理书库，偶尔还会有富有的图书藏家招收他们管理自己的私人藏书。"
        ),
        skill_ids=["accounting", "language-native", "library-use"],
        choice_slots=[
            SkillChoiceSlot(
                count=4,
                candidate_skill_ids=None,
                label="任意四项其他个人特长或专业书籍主题",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "language-foreign-1",
                    "language-foreign-2",
                    "language-foreign-3",
                ],
                label="外语（任一）",
            ),
        ],
    ),
    OccupationSpec(
        id=73,
        name="技师",
        credit_min=9,
        credit_max=40,
        skill_points_formula="EDU*4",
        description=(
            "技师包括所有需要专业训练和作为学徒或实习生工作经验的职业，例如木工、石工、管道工"
            "、电气维修、设备安装工人、机修工人等等这些需要技术资质的职业。通常这些工人有自己"
            "的工会组织，会和承包人和雇主争取自己的权益。"
        ),
        skill_ids=[
            "climb",
            "drive-auto",
            "electrical-repair",
            "heavy-machinery",
            "mechanical-repair",
        ],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["art-craft-1", "art-craft-2", "art-craft-3"],
                label="技艺（木工、焊接、管道工等，任选一项）",
            ),
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=None,
                label="任意两项其他个人或时代或技术特长",
            ),
        ],
    ),
    OccupationSpec(
        id=74,
        name="军官",
        credit_min=20,
        credit_max=70,
        skill_points_formula="EDU*2+MAX(STR,DEX)*2",
        description=(
            "军官有严格的等级，许多等级还需要高等教育学历。各国武装部队都建立了人才培养系统，"
            "其中包括大学教育。在美国，许多大学开设军校生训练项目，可以让学员同时接受文化教育"
            "和军事训练。毕业的学员可以授以陆军或海军少尉军衔，并分派到各驻地。他们通常会为国"
            "家服役四年，之后可以退役覆员。许多人有专门的任命，作为医生、律师和工程师工作。 "
            "寻求军旅生涯的人会为进入西点军校和美国海军军官学校这样的著名军校而努力，拥有这些"
            "名校学历很容易得到其他军官的尊敬。离开学校以后，许多军官也会选择接受飞行训练等特"
            "殊训练。 富有经验，特别值得提升的士兵会被破例提拔为一级准尉。虽然在名义上位列最"
            "末，获得这一军衔所需要的时间和经验意味着他们远比普通的初中级军官更受尊敬。绝大多"
            "数军衔是终身荣誉，退役多年的军官仍然可以自称上尉或者将军。"
        ),
        skill_ids=["accounting", "first-aid", "navigation", "psychology"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "firearm-handgun",
                    "firearm-rifle",
                    "firearm-smg",
                    "firearm-machine-gun",
                    "firearm-bow",
                    "firearm-flamethrower",
                ],
                label="射击（任选一项专精）",
            ),
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="两项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=None,
                label="任意一项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=75,
        name="传教士",
        credit_min=0,
        credit_max=30,
        skill_points_formula="EDU*2+APP*2",
        description=(
            "传教士云游到世界的各个角落，传播神的旨意，在文明的地方拯救“不幸的原始人”和“迷"
            "途的灵魂”。他们可能属于天主教、新教、伊斯兰教或者其他信仰系统，比如后期圣徒教会"
            "(摩门教)在欧美就有专门的传道所。 有的传教士只凭自己的意志独立行动，有的则可能"
            "有教会以外的组织支持。 基督教、伊斯兰教的传教者，佛教、印度教的法师，在全世界各"
            "个时代都能遇到。"
        ),
        skill_ids=["first-aid", "mechanical-repair", "medicine", "natural-world"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["art-craft-1", "art-craft-2", "art-craft-3"],
                label="技艺（任一）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="一项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=None,
                label="任意两项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=76,
        name="登山家",
        credit_min=30,
        credit_max=60,
        skill_points_formula="EDU*2+MAX(STR,DEX)*2",
        description=(
            "登山家一般都是利用业余时间和假期的运动员，只有少数攀登著名高山的人才会去寻找财力"
            "和设备的赞助。 19 世纪登山运动开始兴起，到了1920 年代，所有美洲和阿尔卑"
            "斯地区的主要山峰都被一一征服。经过与西藏人的冗长谈判之后，外国登山队终于获准进入"
            "喜马拉雅山的高峰地区。作为世界上最后未被征服的高峰，对珠峰的进军经常被电台和报纸"
            "报道。不过1921、1922、1924 年的三次远征都没能达到峰顶，还造成了13"
            " 人死亡。 到了现代，登山可以是休闲运动或职业选择。如果是后者，则工作内容包括教"
            "练、向导、运动员或救生员等。 (译注：1920 年代的登山队都是取道中国境内的北"
            "坡，故正是与西藏地方政府进行的商谈。)"
        ),
        skill_ids=["climb", "first-aid", "jump", "listen", "navigation", "survival", "track"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "language-foreign-1",
                    "language-foreign-2",
                    "language-foreign-3",
                ],
                label="外语（任一）",
            ),
        ],
    ),
    OccupationSpec(
        id=77,
        name="博物馆管理员",
        credit_min=10,
        credit_max=30,
        skill_points_formula="EDU*4",
        description=(
            "博物馆管理员可能负责大学或其他公共机构的大型设施，也可能负责小一些的博物馆，往往"
            "对本地的地质或者其他的内容颇有研究。"
        ),
        skill_ids=[
            "accounting",
            "appraise",
            "archaeology",
            "history",
            "library-use",
            "occult",
            "spot-hidden",
        ],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "language-foreign-1",
                    "language-foreign-2",
                    "language-foreign-3",
                ],
                label="外语（任一）",
            ),
        ],
    ),
    OccupationSpec(
        id=78,
        name="音乐家",
        credit_min=9,
        credit_max=30,
        skill_points_formula="EDU*2+MAX(POW,DEX)*2",
        description=(
            "音乐家可能加入乐团、乐队或者独奏，演奏的乐器则可以是任何你能想象的种类。音乐家想"
            "出人头地十分困难，签约发布唱片就更难了。所以绝大多数音乐家都贫穷又无人关注，只靠"
            "街头卖艺勉强维持生计。少数幸运儿可以找到固定工作，比如在酒吧、宾馆或者市交响乐团"
            "弹钢琴。对更少的人来说，在正确的时间出现在正确的地点，再加上一点点天赋，就能获得"
            "巨大的成功和可观的财富。 1920 年代是爵士乐的年代，众多的音乐家在美国各地的"
            "大中城市、城镇里的爵士乐队和交响乐队工作。少数音乐家住在芝加哥和纽约之类的大城市"
            "并在那里打拼，而大部分的人靠巴士、汽车或者火车过着旅行生活。"
        ),
        skill_ids=["listen", "psychology"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="一项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=4,
                candidate_skill_ids=None,
                label="四项其他技能",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["art-craft-1", "art-craft-2", "art-craft-3"],
                label="技艺（任一）",
            ),
        ],
    ),
    OccupationSpec(
        id=79,
        name="护士",
        credit_min=9,
        credit_max=30,
        skill_points_formula="EDU*4",
        description=(
            "护士是专业的医疗助理，通常在医院和疗养院之类的地方工作，或者和全科医生一起合作。"
            "一般来说，护士会协助健康人或病人进行保健或康复活动(或者临终关怀)，虽然其他人若"
            "是有足够的力量、意志或者知识，完全不需要护士帮助的康复也是可能的。"
        ),
        skill_ids=[
            "first-aid",
            "listen",
            "medicine",
            "psychology",
            "science-biology",
            "science-chemistry",
            "spot-hidden",
        ],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="一项社交技能（取悦、话术、恐吓、说服）",
            ),
        ],
    ),
    OccupationSpec(
        id=80,
        name="神秘学家",
        credit_min=9,
        credit_max=65,
        skill_points_formula="EDU*4",
        description=(
            "神秘学家是钻研深奥秘密和神秘魔法的人。他们对超博物学能力深信不疑，并竭尽所能靠他"
            "们的能力去了解这些东西。许多人对不同神秘哲学和魔法理论的知识面都相当广泛，有些甚"
            "至相信自己专注研究三十年真的成为了魔法师——到底是真是假就交由KP 来决断了。 "
            "需要指出的是，神秘学家熟知的基本上是“表面的魔法”——克苏鲁神话魔法的秘密对他们"
            "仍然是未知的，或者不过是古书上描述那些诱人的线索而已。"
        ),
        skill_ids=["anthropology", "history", "library-use", "occult", "science-astronomy"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="一项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=None,
                label="任意一项其他个人或时代特长（经 KP 允许可以包含克苏鲁神话）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "language-foreign-1",
                    "language-foreign-2",
                    "language-foreign-3",
                ],
                label="外语（任一）",
            ),
        ],
    ),
    OccupationSpec(
        id=81,
        name="旅行家",
        credit_min=5,
        credit_max=20,
        skill_points_formula="EDU*2+MAX(STR,DEX)*2",
        description=(
            "旅行家爱好户外，他们一年中大部分时间都呆在户外，并且一出门就是相当长的时间；通常"
            "有相当的捕鱼和狩猎技术，能在最恶劣的环境之中幸存下来。擅长的技术可能包括登山、捕"
            "鱼、滑雪、皮划艇、攀登和露营。 旅行家可能在国家公园或素质拓展中心做野外向导和护"
            "林员，也可能是有其他经济来源能让他们不用工作就能以这种方式生活，说不定还可能是一"
            "个隐士，只有在需要的时候才会回到文明社会。"
        ),
        skill_ids=[
            "first-aid",
            "listen",
            "natural-world",
            "navigation",
            "spot-hidden",
            "survival",
            "track",
        ],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "firearm-handgun",
                    "firearm-rifle",
                    "firearm-smg",
                    "firearm-machine-gun",
                    "firearm-bow",
                    "firearm-flamethrower",
                ],
                label="射击（选择一项专精）",
            ),
        ],
    ),
    OccupationSpec(
        id=82,
        name="超心理学家",
        credit_min=9,
        credit_max=30,
        skill_points_formula="EDU*4",
        description=(
            "超心理学家从不打算欣赏超常现象。相反，他们试图去观察，记录并研究这些实例。被叫做"
            "“捉鬼人”的他们利用技术手段来获取某人或某地点的超博物学活动的证据，当然比起收集"
            "到实在的证据，更多的时候他们是在揭穿假冒和误认的超常现象。 一些超心理学家专门研"
            "究特定的现象，例如超感官、心灵致动、闹鬼等等。 名牌大学是没有超心理学学位的。这"
            "个领域成就的评判标准完全是基于个人声誉，所以一般有相近学科学历比如物理学、心理学"
            "和医学的人会比较有说服力。 选择研究这个的人往往对不可视的神秘力量抱有相当的同情"
            "态度，并希望其他的科学家也能满意地点头肯定。这就表现出了一种既相信又怀疑的奇异的"
            "迭加态——恐怕超心理学家自己也难解决这个问题。一个对观察实验证明不感兴趣的人是个"
            "神秘学家而不是个科学家。"
        ),
        skill_ids=["anthropology", "history", "library-use", "occult", "photography", "psychology"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "language-foreign-1",
                    "language-foreign-2",
                    "language-foreign-3",
                ],
                label="外语（选择一门）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=None,
                label="任意一项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=83,
        name="药剂师",
        credit_min=35,
        credit_max=75,
        skill_points_formula="EDU*4",
        description=(
            "药剂师的管理一直以来都比医生更严格。所有的药剂师都要在各州注册，注册的条件则是高"
            "中毕业并至少在药学院学习三年。他们可能在医院或者药房工作，也可能自己开药房。"
        ),
        skill_ids=[
            "accounting",
            "first-aid",
            "library-use",
            "psychology",
            "science-chemistry",
            "science-pharmacy",
        ],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="一项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "language-foreign-1",
                    "language-foreign-2",
                    "language-foreign-3",
                ],
                label="外语（任一）",
            ),
        ],
    ),
    OccupationSpec(
        id=84,
        name="摄影师-摄影师",
        credit_min=9,
        credit_max=30,
        skill_points_formula="EDU*4",
        description=(
            "摄影师大部分是自由工作者，可能制作广告电影或者在照相馆做肖像拍摄。其他一些摄像师"
            "则在报纸、电视和电影产业工作。 摄影作为一种艺术形式已经产生相当长的时间了，精英"
            "的摄影师可以从艺术、新闻报道、野生动物保护等多种角度出发创作他们的作品。不管是哪"
            "种立意，他们都能获得名誉和报酬。 摄影记者本质上就是拿照相机，为拍摄的照片写配文"
            "的记者。在1920 年代，新闻短片走上历史舞台。笨重的35mm 摄像装备走遍全球"
            "各地，搜寻有价值的新闻轶事、体育赛事和泳装选美比赛。新闻片制作人员一般分为三类："
            "一类是画面中的记者，另两个人则负责摄像和灯光等等。新闻中的声音则是在新闻稿完成以"
            "后在录音棚中录入完成的。"
        ),
        skill_ids=["photography", "psychology", "science-chemistry", "spot-hidden", "stealth"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="一项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=None,
                label="任意两项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=85,
        name="摄影师-摄影记者",
        credit_min=10,
        credit_max=30,
        skill_points_formula="EDU*4",
        description=(
            "摄影师大部分是自由工作者，可能制作广告电影或者在照相馆做肖像拍摄。其他一些摄像师"
            "则在报纸、电视和电影产业工作。 摄影作为一种艺术形式已经产生相当长的时间了，精英"
            "的摄影师可以从艺术、新闻报道、野生动物保护等多种角度出发创作他们的作品。不管是哪"
            "种立意，他们都能获得名誉和报酬。 摄影记者本质上就是拿照相机，为拍摄的照片写配文"
            "的记者。在1920 年代，新闻短片走上历史舞台。笨重的35mm 摄像装备走遍全球"
            "各地，搜寻有价值的新闻轶事、体育赛事和泳装选美比赛。新闻片制作人员一般分为三类："
            "一类是画面中的记者，另两个人则负责摄像和灯光等等。新闻中的声音则是在新闻稿完成以"
            "后在录音棚中录入完成的。"
        ),
        skill_ids=["climb", "photography", "psychology", "science-chemistry"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="一项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "language-foreign-1",
                    "language-foreign-2",
                    "language-foreign-3",
                ],
                label="外语（选择一门）",
            ),
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=None,
                label="任意两项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=86,
        name="飞行员-飞行员",
        credit_min=20,
        credit_max=70,
        skill_points_formula="EDU*2+DEX*2",
        description=(
            "飞行员可以在美国邮政这样的企业工作，也可以在大大小小的民航公司做飞行人员。 美国"
            "1926 年之前没有对飞行员的职业要求，1926 年航空商业法案通过之后才要求有"
            "执照。这个时代的多数飞行员从事嘉年华表演、特技飞行表演、乘飞机游玩或是小机场的空"
            "中的士等服务。 也有飞行员在部队服现役。许多特技飞行员是在服役期间学会的驾驶飞机"
            "，有时仍然会被军队委派任务。"
        ),
        skill_ids=[
            "electrical-repair",
            "heavy-machinery",
            "mechanical-repair",
            "navigation",
            "pilot-aircraft",
            "science-astronomy",
        ],
        choice_slots=[
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=None,
                label="任意两项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=87,
        name="飞行员-特技飞行员（古典）",
        credit_min=30,
        credit_max=60,
        skill_points_formula="EDU*4",
        description=(
            "特技飞行员在嘉年华工作或者为大胆的消费者进行休闲飞行服务。参加有组织的飞行表演赛"
            "，不论是固定路线还是越野赛，往往都可以增加自己的知名度。在1920 年代，好莱坞"
            "常常使用特技飞行员，飞机制造商也会录用一些飞行员为新机作测试。许多特技飞行员是在"
            "一次大战中掌握的飞行技术，所以许多人仍然在陆海空军或海岸警卫队服役；年轻的飞行员"
            "则基本上是在和平时期接受的训练或是自学成才。 参加过一战的王牌飞行员“现在”还活"
            "跃在公众视野中的包括：埃迪·里肯巴克，现在在克赖斯勒公司工作；汤米·希区柯克，“"
            "现在”是马球赛场的明星；里德·兰迪斯，美国职棒大联盟执行长凯纳索·蒙顿·兰迪斯的"
            "儿子。"
        ),
        skill_ids=[
            "accounting",
            "electrical-repair",
            "listen",
            "mechanical-repair",
            "navigation",
            "pilot-aircraft",
            "spot-hidden",
        ],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=None,
                label="任意一项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=88,
        name="警方(原作向)-警探",
        credit_min=20,
        credit_max=50,
        skill_points_formula="EDU*2+MAX(STR,DEX)*2",
        description=(
            "便衣警察的工作是检查犯罪现场、收集证据、询问证人以解决凶杀、盗窃等重大案件。他们"
            "在现场办案中往往与穿制服的巡警密切合作。 警探可能指挥他的下属进行详尽的调查，但"
            "是很难有机会集中精力对付单独一个事件，在美国他们很可能要同时处理数十乃至上百的案"
            "件。警探工作最关键的部分是通过梳理证词、重建现场情况，摒弃伪证，从而收集足够逮捕"
            "嫌疑人的证据，进而促成成功的刑事审判。警探和检察官的职责是分开的，这样可以保证证"
            "据在审判之前被独立地对待。 尽管现在警探通常会参加警察学校课程并获得学位、参加特"
            "殊训练或公务员培训，他们最主要的经验还是来源于担任基层警官或者普通巡警时的工作经"
            "历。"
        ),
        skill_ids=["law", "listen", "psychology", "spot-hidden"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["art-craft-1", "art-craft-2", "art-craft-3"],
                label="技艺（表演）或乔装",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "firearm-handgun",
                    "firearm-rifle",
                    "firearm-smg",
                    "firearm-machine-gun",
                    "firearm-bow",
                    "firearm-flamethrower",
                ],
                label="射击（选择一项专精）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="一项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=None,
                label="一项其他技能",
            ),
        ],
    ),
    OccupationSpec(
        id=89,
        name="警方(原作向)-巡警",
        credit_min=9,
        credit_max=30,
        skill_points_formula="EDU*2+MAX(STR,DEX)*2",
        description=(
            "巡警属于市、城镇、县治安部门或州、地区的警察机关。他们工作时可能步行、驾驶巡逻车"
            "，或者干脆坐办公室。"
        ),
        skill_ids=["fighting-brawl", "first-aid", "law", "psychology", "spot-hidden"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "firearm-handgun",
                    "firearm-rifle",
                    "firearm-smg",
                    "firearm-machine-gun",
                    "firearm-bow",
                    "firearm-flamethrower",
                ],
                label="射击（选择一项专精）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="一项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["drive-auto", "ride"],
                label="下面的一种个人特长：汽车驾驶或骑乘",
            ),
        ],
    ),
    OccupationSpec(
        id=90,
        name="私家侦探",
        credit_min=9,
        credit_max=30,
        skill_points_formula="EDU*2+MAX(STR,DEX)*2",
        description=(
            "私家侦探通常在警察不出手的地方活跃，包括收集证据为客户准备民事诉讼，追查跑路的配"
            "偶或生意伙伴，或者代理刑事案件的私人辩护。他们和任何专业人员一样，私家侦探从不顾"
            "及自己的私人情感，只要付钱，不管是有罪还是无罪的一方的委托他们都乐得接受。 私家"
            "侦探过去可能在警察队伍里工作，利用以前的业务关系为现在工作谋求优势；然而事实并非"
            "总是如此。在许多地方私家侦探必须持证上岗，假如被发现有违法行为，就会撤销执照——"
            "侦探生涯也就到此为止。"
        ),
        skill_ids=["disguise", "law", "library-use", "photography", "psychology", "spot-hidden"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="一项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=None,
                label="一项其他个人或时代特长（如计算机、锁匠、格斗、射击）",
            ),
        ],
    ),
    OccupationSpec(
        id=91,
        name="教授（原作向）",
        credit_min=20,
        credit_max=70,
        skill_points_formula="EDU*4",
        description=(
            "教授是受聘于高等院校的学者。大公司也可 能聘请他们以开展学术研究与产品开发。独立"
            "的学者也靠开办业余课程作为经济来源。 最重要的一点,这一职业代表了 PhD(博士"
            ") 的荣誉称号,意味着可以在世界各地的大学任终身教职。教授的专长是教学和专业研究"
            ",往往在自己的专业领域内有着可圈可点的学术成就。"
        ),
        skill_ids=["language-native", "library-use", "psychology"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "language-foreign-1",
                    "language-foreign-2",
                    "language-foreign-3",
                ],
                label="外语（选择一门）",
            ),
            SkillChoiceSlot(
                count=4,
                candidate_skill_ids=None,
                label="任意四项其他学术、时代或个人特长",
            ),
        ],
    ),
    OccupationSpec(
        id=92,
        name="淘金客",
        credit_min=0,
        credit_max=10,
        skill_points_formula="EDU*2+MAX(STR,DEX)*2",
        description=(
            "淘金客一直是美国西部的特色,即便在加利福尼亚淘金热和内华达康姆斯塔克发现金银矿的"
            "日子早已经过去的现在。他们无休止地在山间漫游,寻找能使自己一夜暴富的矿脉。而且现"
            "在发现石油和发现金子一样给力。"
        ),
        skill_ids=[
            "climb",
            "first-aid",
            "history",
            "mechanical-repair",
            "navigation",
            "science-geology",
            "spot-hidden",
        ],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=None,
                label="任意一项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=93,
        name="性工作者",
        credit_min=5,
        credit_max=50,
        skill_points_formula="EDU*2+APP*2",
        description=(
            "性工作者根据场合、背景和教养,从超级值钱的应召小姐到牛郎再到站街女都有可能。往往"
            "入这一行都是权宜之计,许多人梦想有朝一日能够脱身。少数人能够自己接客,不过绝大多"
            "数人 基本都是被只认钱不认人的老鸨和皮条客逼迫着 工作。"
        ),
        skill_ids=["dodge", "psychology", "sleight-of-hand", "stealth"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["art-craft-1", "art-craft-2", "art-craft-3"],
                label="技艺（任一）",
            ),
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="两项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=None,
                label="任意一项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=94,
        name="精神病学家",
        credit_min=30,
        credit_max=80,
        skill_points_formula="EDU*4",
        description=(
            "精神病学家是在现代专门从事精神失常诊断和治疗的医生。精神病学家掌握着精神药理学的"
            " 治疗方法,使用精神类药物的资质,还能整理脑电图并对其进行计算器分析。 在十九二"
            "十世纪之交,精神分析理论刚刚产 生,试图解释一些现在认为实际上是生物学范畴的现象"
            "。所以,精神分析学家们努力寻求获得自 己的医疗证书。与此同时,各种不同的精神失常"
            "诊断与治疗理论开始起步。到 1930 年代,任何一个医生都可以以精神病学家的身份"
            "进入美国医学协会名录中了。"
        ),
        skill_ids=[
            "listen",
            "medicine",
            "persuade",
            "psychoanalysis",
            "psychology",
            "science-biology",
            "science-chemistry",
        ],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "language-foreign-1",
                    "language-foreign-2",
                    "language-foreign-3",
                ],
                label="外语（任一）",
            ),
        ],
    ),
    OccupationSpec(
        id=95,
        name="心理学家、精神分析学家",
        credit_min=10,
        credit_max=40,
        skill_points_formula="EDU*4",
        description=(
            "心理学家虽然也经常被叫做心理治疗师和心理咨询师,不过这些工作都只是心理学的分支。"
            "其他的还有为企业和政府提供顾问的组织管理心 理学家,进行研究并在学校教授心理学的"
            "学术型心理学家等等。 临床心理学家可能实际接触病人,并且运用各种可能的心理治疗方"
            "法。注意心理学家和专业的精神病学家的区别,后者本质上还是医生。 在1920 年代"
            ",对人类行为的研究还是一个新兴的领域,主要的理论还是弗洛伊德心理学。"
        ),
        skill_ids=[
            "accounting",
            "library-use",
            "listen",
            "persuade",
            "psychoanalysis",
            "psychology",
        ],
        choice_slots=[
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=None,
                label="任意两项其他学术、个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=96,
        name="研究员",
        credit_min=9,
        credit_max=30,
        skill_points_formula="EDU*4",
        description=(
            "学术界的研究课题不计其数,尤其是在天文 学、物理学和其他理论领域。私人或企业也雇"
            "用 了成千上万的研究员,重点在化学、制药和工程 领域。石油公司则会聘用专业的地质"
            "学家,不一 而足。研究员大部分的时间都在室内工作和写作, 不过有的则会经常外出考"
            "察。 考察研究员通常经验丰富,思想独立又足智 多谋,可能受雇于私人或者为大学进行"
            "学术研究。 石油公司会派出地质学家探索潜在的油田, 人类学家则是调查地球被人遗忘"
            "角落的原始部落, 考古学家则竭数年之力挖掘沙漠丛林之中的宝藏, 还要和工人与地方"
            "政府打交道。"
        ),
        skill_ids=["history", "library-use", "spot-hidden"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="一项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "language-foreign-1",
                    "language-foreign-2",
                    "language-foreign-3",
                ],
                label="外语（选择一门）",
            ),
            SkillChoiceSlot(
                count=3,
                candidate_skill_ids=None,
                label="任意三项其他学术领域",
            ),
        ],
    ),
    OccupationSpec(
        id=97,
        name="海员-军舰海员",
        credit_min=9,
        credit_max=30,
        skill_points_formula="EDU*2+MAX(DEX,STR)*2",
        description=(
            "新入伍的海员像陆军的同行一样,开始时需 要接受基本的训练。这之后他们获得军衔,并"
            "被 分配到各镇守府。虽然很多海员担任像水手长副手和司炉工(管理引擎)这样的传统角"
            "色,但是也有很多经过专门训练的机械师、无线电操作员、通风管理员之类。海员们最高的"
            "军衔是士官长, 达到了这个军衔连高级将领都要礼让三分。在美国,海员通常要服四年的"
            "现役和后两年的后备役, 即在国家发布动员令时有应召服役的义务。"
        ),
        skill_ids=["first-aid", "navigation", "pilot-boat", "survival", "swim"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["electrical-repair", "mechanical-repair"],
                label="电工或机械维修",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "fighting-brawl",
                    "fighting-sword",
                    "fighting-axe",
                    "fighting-spear",
                    "fighting-whip",
                    "fighting-chain",
                    "fighting-knife",
                ],
                label="格斗（任选一种专精）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "firearm-handgun",
                    "firearm-rifle",
                    "firearm-smg",
                    "firearm-machine-gun",
                    "firearm-bow",
                    "firearm-flamethrower",
                ],
                label="射击（任选一种专精）",
            ),
        ],
    ),
    OccupationSpec(
        id=98,
        name="海员-民船海员",
        credit_min=20,
        credit_max=40,
        skill_points_formula="EDU*2+MAX(DEX,STR)*2",
        description=(
            "民用船海员可能在渔船、客船,或运输原油或商品的运输船上工作。在美国,客船活跃在东"
            "西海岸和五大湖,运送渔民和游客。目前佛罗里达州在墨西哥湾和大西洋海岸拥有最多数量"
            "的客 船。 在禁酒令期间,许多客船船长发现把急切想 喝酒的顾客运到 3 海里外,"
            "外国船只允许卖酒的地方是一桩赚钱的买卖。当然走私酒也报酬丰厚, 但是危险就高多了"
            "。"
        ),
        skill_ids=[
            "first-aid",
            "mechanical-repair",
            "natural-world",
            "navigation",
            "pilot-boat",
            "spot-hidden",
            "swim",
        ],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="一项社交技能（取悦、话术、恐吓、说服）",
            ),
        ],
    ),
    OccupationSpec(
        id=99,
        name="推销员",
        credit_min=9,
        credit_max=40,
        skill_points_formula="EDU*2+APP*2",
        description=(
            "推销员是商务工作的必需一环,他们的工作就是推广和销售公司的产品或服务。大部分推销"
            "员的时间要用来旅行、开会、和客户应酬(在报销限额之内)。有些则主要坐办公室用电话"
            "联系 潜在客户,还有的会在各小区巡回,挨家挨户上门推销。 1920 年代是企业家"
            "的年代,旅行推销成了一种日常生活方式。这些人有些直接现货交易,有些通过托销交易,"
            "当然不管黑猫白猫,拿到订单的才是好猫,推销员要用强烈的销售策略才能说得客户,至于"
            "价钱就不是他们考虑的范围了。有些推销员在固定的地区工作,有些则可以自由漫 游,寻"
            "找任何地方可能出现的商机。如果是上门推销,那商品可能就是刷子、吸尘器或者百科全书"
            "之类的各种对象了。"
        ),
        skill_ids=["accounting", "drive-auto", "listen", "psychology"],
        choice_slots=[
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="两项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["stealth", "sleight-of-hand"],
                label="潜行或妙手",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=None,
                label="一项其他技能",
            ),
        ],
    ),
    OccupationSpec(
        id=100,
        name="科学家",
        credit_min=9,
        credit_max=50,
        skill_points_formula="EDU*4",
        description=(
            "科学家是在追求知识的过程中挖掘真理的人。如果想要利用科学知识制造有用的物品,需要"
            "的 是工程师;而如果想要扩展“可能”这个概念的范围,那就是科学家的工作了。 科学"
            "家们通常在企业和大学工作,以进行他们的研究。 虽然主攻一个科学领域,但是真正称职"
            "的科 学家一般也能达到通晓其他数个科学领域的水平。他们对自己的母语也能使用自如,"
            "学历也相当高, 甚至拥有博士学位。"
        ),
        skill_ids=["language-native", "spot-hidden"],
        choice_slots=[
            SkillChoiceSlot(
                count=3,
                candidate_skill_ids=[
                    "science-pharmacy",
                    "science-biology",
                    "science-chemistry",
                    "science-physics",
                    "science-geology",
                    "science-astronomy",
                    "science-forensics",
                    "science-mathematics",
                    "science-engineering",
                    "science-botany",
                    "science-zoology",
                    "science-cryptography",
                    "science-metallurgy",
                    "science-meteorology",
                ],
                label="任意三项科学专业领域",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["computer-use", "library-use"],
                label="计算机或图书馆",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "language-foreign-1",
                    "language-foreign-2",
                    "language-foreign-3",
                ],
                label="外语（任一）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="一项社交技能（取悦、话术、恐吓、说服）",
            ),
        ],
    ),
    OccupationSpec(
        id=101,
        name="秘书",
        credit_min=9,
        credit_max=30,
        skill_points_formula="EDU*2+MAX(DEX,APP)*2",
        description=(
            "秘书的范围是从高薪的私人管理助理到普通的打字员。这份工作的重点在于以自己各种沟通"
            " 协调能力,支持主管和经理人员。 因为身处企业流程的中心,许多秘书比老板对企业的"
            "内部运作和经营还要熟悉。 在 1920 年代,秘书工作主要是通信工作,例如听写打"
            "印信件,整理文文件系统,并为老板安排 会议时间。有的情况下,秘书还会负责老板的生"
            "活, 比如安排假期、为老板和家人置办礼物,还有保 护老板的安全。"
        ),
        skill_ids=["accounting", "language-native", "psychology"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["art-craft-1", "art-craft-2", "art-craft-3"],
                label="技艺（打字或速记）",
            ),
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="两项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["library-use", "computer-use"],
                label="图书馆或计算机",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=None,
                label="任意一项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=102,
        name="店老板",
        credit_min=20,
        credit_max=40,
        skill_points_formula="EDU*2+MAX(APP,DEX)*2",
        description=(
            "店老板经营小店、市场摊位或者是小饭馆。这种店往往都是小本自营,不过也有为其他东家"
            "照顾生意的。不少店是家族式管理,工作人员大 部分都有亲属关系,其他的雇员即便有也"
            "很少。 在 1920 年代,还有不少的老板娘开起了自己的理发店和帽店。"
        ),
        skill_ids=[
            "accounting",
            "electrical-repair",
            "listen",
            "mechanical-repair",
            "psychology",
            "spot-hidden",
        ],
        choice_slots=[
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="两项社交技能（取悦、话术、恐吓、说服）",
            ),
        ],
    ),
    OccupationSpec(
        id=103,
        name="士兵、海军陆战队士兵",
        credit_min=9,
        credit_max=30,
        skill_points_formula="EDU*2+MAX(STR,DEX)*2",
        description=(
            "士兵指的是从列兵到士官长(美国军衔制) 的统称。尽管名义上比起最新的次级少尉还低"
            ", 即便高级军官也往往对他们给予尊重。在美国, 标准的服役期限是六年,包括四年现"
            "役和两年后 备役。 所有应征人员首先要在“训练营(新兵连)” 接受基本训练,在训"
            "练营中新兵将学习如何行军、 射击和敬礼。结束训练营的训练后,大部分的新兵会分配到"
            "步兵营,虽然也有分配到炮兵营和坦 克营的。少部分会接受非战斗的训练,例如通风 系"
            "统、机械装备、文职甚至军官接待。海军陆战队名义上属于海军,但是和陆军士兵在背景、"
            "训练方式和技能方面都很相近。"
        ),
        skill_ids=["dodge", "stealth", "survival"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["climb", "swim"],
                label="攀爬或游泳",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "fighting-brawl",
                    "fighting-sword",
                    "fighting-axe",
                    "fighting-spear",
                    "fighting-whip",
                    "fighting-chain",
                    "fighting-knife",
                ],
                label="格斗（任选一种专精）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "firearm-handgun",
                    "firearm-rifle",
                    "firearm-smg",
                    "firearm-machine-gun",
                    "firearm-bow",
                    "firearm-flamethrower",
                ],
                label="射击（任选一种专精）",
            ),
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=[
                    "language-foreign-1",
                    "language-foreign-2",
                    "language-foreign-3",
                ],
                label="下面任选两项：急救、机械维修、外语",
            ),
        ],
    ),
    OccupationSpec(
        id=104,
        name="间谍",
        credit_min=20,
        credit_max=60,
        skill_points_formula="EDU*2+MAX(APP,DEX)*2",
        description=(
            "间谍为国家和组织的情报部门卖命。他们能以从大使到厨房清洁工的任何职业身份作为掩饰"
            ",刺探他们所需的情报。有些间谍数年如一日的持续着卧底工作,另一些穿个马甲就换一个"
            "身份。 在本国委任的间谍通常会去往外国工作。间谍除了情报收集和反情报收集的主要工"
            "作, 也会被委派其他任务,例如招募新间谍和国家批 准的暗杀等。"
        ),
        skill_ids=["listen", "psychology", "sleight-of-hand", "stealth"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["art-craft-1", "art-craft-2", "art-craft-3"],
                label="技艺（表演）或乔装",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "firearm-handgun",
                    "firearm-rifle",
                    "firearm-smg",
                    "firearm-machine-gun",
                    "firearm-bow",
                    "firearm-flamethrower",
                ],
                label="射击（任一）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "language-foreign-1",
                    "language-foreign-2",
                    "language-foreign-3",
                ],
                label="外语（任一）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="一项社交技能（取悦、话术、恐吓、说服）",
            ),
        ],
    ),
    OccupationSpec(
        id=105,
        name="学生、实习生",
        credit_min=5,
        credit_max=10,
        skill_points_formula="EDU*4",
        description=(
            "学生可能在大学或学院学习,实习生则是正在接受宝贵的入职培训,获得最低报酬的公司员 工。"
        ),
        skill_ids=["library-use", "listen"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "language-foreign-1",
                    "language-foreign-2",
                    "language-foreign-3",
                ],
                label="语言（母语或外语）",
            ),
            SkillChoiceSlot(
                count=3,
                candidate_skill_ids=None,
                label="三个学习的专业",
            ),
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=None,
                label="任意两项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=106,
        name="替身演员",
        credit_min=10,
        credit_max=50,
        skill_points_formula="EDU*2+MAX(STR,DEX)*2",
        description=(
            "替身演员在电影和电视剧工业中活跃,专门 模拟坠楼、车祸等灾难场景。他们通常会接受"
            "格 斗技巧和舞台格斗的训练。任何的替身特技表演 都是有风险的,所以健康和安全是这"
            "个工作的核心元素。 在现代,替身演员基本都是工会的成员,想要加入工会,他们必须有"
            "证明自己能力的证书(例 如高级驾驶执照,潜水执照等等)。而且,所有 的特技场景还"
            "要有特技总监负责指导动作。但是在 1920 年代,这些演员组织、行业规范根本就没"
            "有成型,所以事故率和死亡率居高不下。"
        ),
        skill_ids=["climb", "dodge", "first-aid", "jump", "swim"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["electrical-repair", "mechanical-repair"],
                label="电气维修或机械维修",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "fighting-brawl",
                    "fighting-sword",
                    "fighting-axe",
                    "fighting-spear",
                    "fighting-whip",
                    "fighting-chain",
                    "fighting-knife",
                ],
                label="格斗（任一）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "diving",
                    "drive-auto",
                    "drive-carriage",
                    "pilot-aircraft",
                    "pilot-boat",
                    "pilot-spacecraft",
                    "ride",
                ],
                label="下面任选一项：潜水、汽车驾驶、驾驶（任一）、骑乘",
            ),
        ],
    ),
    OccupationSpec(
        id=107,
        name="部落成员",
        credit_min=0,
        credit_max=15,
        skill_points_formula="EDU*2+MAX(STR,DEX)*2",
        description=(
            "至少,从家族忠诚来说,部落文化无处不在。在部落中,亲属关系和传统习俗的首䙳地位是"
            "不言而喻的。一个部落通常来说是一个相对较小的群体。相比起法律和个人权利,部落更加"
            "依据个人荣耀而裁定行为。崇拜、复仇、嘉奖以及荣耀－－所有的一切都是部落成员个人所"
            "有的,而如果领袖或是仇敌被视为有荣耀的人,那么他们个人也必然在某种程度上十分有名"
            "。在这样的环境下, 放逐是有着实际的效用在的。"
        ),
        skill_ids=["climb", "listen", "natural-world", "occult", "spot-hidden", "survival", "swim"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "fighting-brawl",
                    "fighting-sword",
                    "fighting-axe",
                    "fighting-spear",
                    "fighting-whip",
                    "fighting-chain",
                    "fighting-knife",
                    "throw",
                ],
                label="格斗或投掷",
            ),
        ],
    ),
    OccupationSpec(
        id=108,
        name="殡葬师",
        credit_min=20,
        credit_max=40,
        skill_points_formula="EDU*4",
        description=(
            "殡葬师又叫殡葬业者或葬礼主持人,是负责运行丧葬仪式的职业。工作也包含土葬和火化等"
            "内容。在葬礼上,殡葬师要进行防腐、裹衣、入殓、 遗体美容等等工作。 殡葬师的执照"
            "由各州发放。他们可能自己拥有殡仪馆,或者在别人的殡仪馆工作。"
        ),
        skill_ids=[
            "accounting",
            "drive-auto",
            "history",
            "occult",
            "psychology",
            "science-biology",
            "science-chemistry",
        ],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="一项社交技能（取悦、话术、恐吓、说服）",
            ),
        ],
    ),
    OccupationSpec(
        id=109,
        name="工会活动家",
        credit_min=5,
        credit_max=50,
        skill_points_formula="EDU*4",
        description=(
            "工会活动家是组织者、领导者,有时也是空 想者或者别有用心的抗议者,通常是工人的伙"
            "伴、 老板的对头。各行各业都有工会,不论是码头工人、 建筑工人、矿工还是演员。 "
            "在 20 世纪早期,工会活动家所在的工会面临着诸多危险。大企业想要毁掉它,政治家"
            "在支持它和谴责它之间摇摆不定,社会主义者和共产主义者试图影响它,还有犯罪组织试图"
            "夺取它。"
        ),
        skill_ids=[
            "accounting",
            "fighting-brawl",
            "heavy-machinery",
            "law",
            "listen",
            "psychology",
        ],
        choice_slots=[
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="两项社交技能（取悦、话术、恐吓、说服）",
            ),
        ],
    ),
    OccupationSpec(
        id=110,
        name="服务生",
        credit_min=9,
        credit_max=20,
        skill_points_formula="EDU*2+MAX(APP,DEX)*2",
        description=(
            "服务生在酒店、酒吧或者其他餐饮业场所服务顾客。通常薪酬很低,不过通过对顾客良好服"
            "务, 可以得到他们给的小费。 在禁酒令时期,售酒场所的服务员是非法职业。不过犯罪"
            "组织把控的地下酒吧中仍然存在许多工作机会。"
        ),
        skill_ids=["accounting", "dodge", "listen", "psychology"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["art-craft-1", "art-craft-2", "art-craft-3"],
                label="技艺（任一）",
            ),
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="两项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=None,
                label="任意一项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=111,
        name="白领工人-职员、主管",
        credit_min=9,
        credit_max=20,
        skill_points_formula="EDU*4",
        description=(
            "白领工人可能是从最低等级的白领职员到中层或高层的管理人员。所属单位则可能从小型中"
            "型的本地企业直到大型的国家级甚至跨国公司。 职员被扣工资是家常便饭,工作也往往单"
            "调乏味。不过如果在工作中展现出了天分,那也会被看上,将来会得到提拔。"
        ),
        skill_ids=["accounting", "law", "listen"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "language-foreign-1",
                    "language-foreign-2",
                    "language-foreign-3",
                ],
                label="语言（母语或外语）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["library-use", "computer-use"],
                label="图书馆或计算机",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="一项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=None,
                label="任意两项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=112,
        name="白领工人-中高层管理人员",
        credit_min=20,
        credit_max=80,
        skill_points_formula="EDU*4",
        description=(
            "白领工人可能是从最低等级的白领职员到中层或高层的管理人员。所属单位则可能从小型中"
            "型的本地企业直到大型的国家级甚至跨国公司。 中高层管理人员的工 资比较高,当然责"
            "任也比较重,要负责管理公司的日常事务。虽然未婚的白领并不少见,但很多管理人员还是"
            "很顾家,家里一般会有配偶和孩子——家庭通常是他们的期望。"
        ),
        skill_ids=["accounting", "law", "psychology"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "language-foreign-1",
                    "language-foreign-2",
                    "language-foreign-3",
                ],
                label="外语（任一）",
            ),
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="两项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=None,
                label="任意两项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=113,
        name="狂热者",
        credit_min=0,
        credit_max=30,
        skill_points_formula="EDU*2+MAX(APP,POW)*2",
        description=(
            "热情而有动力、鄙视安逸的生活,狂热者们为人类更好的生活或者为人类中最精华部分的利"
            "益而躁动不安。一些狂热者通过暴力推进他们的信仰,但是并不能说采取和平方式的就比他"
            "们好说话,他们每个人都梦想着为自己的理想辩护。"
        ),
        skill_ids=["history", "psychology", "stealth"],
        choice_slots=[
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="两项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=3,
                candidate_skill_ids=None,
                label="任意三项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=114,
        name="饲养员",
        credit_min=9,
        credit_max=40,
        skill_points_formula="EDU*4",
        description=(
            "饲养员负责动物的喂养和看护,场地管理员和服务员管理其他杂务。通常饲养员会专门照看"
            "某一种动物,可以对动物使用「医学」技能。"
        ),
        skill_ids=[
            "accounting",
            "animal-handling",
            "dodge",
            "first-aid",
            "medicine",
            "natural-world",
            "science-pharmacy",
            "science-zoology",
        ],
    ),
    OccupationSpec(
        id=115,
        name="大使",
        credit_min=50,
        credit_max=90,
        skill_points_formula="EDU*2+APP*2",
        description="《克苏鲁的呼唤调查员伴侣》职业，使用前请征得KP同意。",
        skill_ids=[
            "charm",
            "fast-talk",
            "history",
            "intimidate",
            "language-native",
            "listen",
            "persuade",
            "psychology",
        ],
    ),
    OccupationSpec(
        id=116,
        name="运动员（游泳/潜水）",
        credit_min=9,
        credit_max=20,
        skill_points_formula="EDU*2+MAX(STR,DEX)*2",
        description="《克苏鲁的呼唤调查员伴侣》职业，使用前请征得KP同意。",
        skill_ids=["climb", "fighting-brawl", "jump", "swim", "throw"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="一项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=None,
                label="任意一项其他个人或时代特长",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "language-foreign-1",
                    "language-foreign-2",
                    "language-foreign-3",
                ],
                label="外语（任一）",
            ),
        ],
    ),
    OccupationSpec(
        id=117,
        name="运动员（高尔夫）",
        credit_min=50,
        credit_max=70,
        skill_points_formula="EDU*2+MAX(STR,DEX)*2",
        description="《克苏鲁的呼唤调查员伴侣》职业，使用前请征得KP同意。",
        skill_ids=["climb", "fighting-brawl", "jump", "ride", "swim", "throw"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="一项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=None,
                label="任意一项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=118,
        name="运动员（网球）",
        credit_min=30,
        credit_max=70,
        skill_points_formula="EDU*2+MAX(STR,DEX)*2",
        description="《克苏鲁的呼唤调查员伴侣》职业，使用前请征得KP同意。",
        skill_ids=["dodge", "fighting-brawl", "jump", "psychology", "spot-hidden", "throw"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="一项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=None,
                label="任意一项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=119,
        name="运动员（田径）",
        credit_min=9,
        credit_max=20,
        skill_points_formula="EDU*2+MAX(STR,DEX)*2",
        description="《克苏鲁的呼唤调查员伴侣》职业，使用前请征得KP同意。",
        skill_ids=["climb", "dodge", "fighting-brawl", "jump", "throw"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="一项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=None,
                label="任意一项其他个人或时代特长",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "language-foreign-1",
                    "language-foreign-2",
                    "language-foreign-3",
                ],
                label="外语（任一）",
            ),
        ],
    ),
    OccupationSpec(
        id=120,
        name="发言人",
        credit_min=50,
        credit_max=80,
        skill_points_formula="EDU*4",
        description="《克苏鲁的呼唤调查员伴侣》职业，使用前请征得KP同意。",
        skill_ids=["disguise", "dodge", "psychology"],
        choice_slots=[
            SkillChoiceSlot(
                count=3,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="三项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=None,
                label="任意一项其他个人或时代特长",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "language-foreign-1",
                    "language-foreign-2",
                    "language-foreign-3",
                ],
                label="外语（任一）",
            ),
        ],
    ),
    OccupationSpec(
        id=121,
        name="保释担保人",
        credit_min=50,
        credit_max=80,
        skill_points_formula="EDU*4",
        description="《克苏鲁的呼唤调查员伴侣》职业，使用前请征得KP同意。",
        skill_ids=["accounting", "law", "library-use", "psychology"],
        choice_slots=[
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="两项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=None,
                label="任意两项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=122,
        name="神职人员(天主教牧师)",
        credit_min=20,
        credit_max=70,
        skill_points_formula="EDU*4",
        description="《克苏鲁的呼唤调查员伴侣》职业，使用前请征得KP同意。",
        skill_ids=["accounting", "language-native", "library-use", "occult", "psychology"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="一项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=None,
                label="任意一项其他技能",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "language-foreign-1",
                    "language-foreign-2",
                    "language-foreign-3",
                ],
                label="外语（任一）",
            ),
        ],
    ),
    OccupationSpec(
        id=123,
        name="神职人员(新教牧师)",
        credit_min=9,
        credit_max=60,
        skill_points_formula="EDU*4",
        description="《克苏鲁的呼唤调查员伴侣》职业，使用前请征得KP同意。",
        skill_ids=["accounting", "history", "library-use", "listen", "psychology"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="一项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=None,
                label="任意一项其他技能",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "language-foreign-1",
                    "language-foreign-2",
                    "language-foreign-3",
                ],
                label="外语（任一）",
            ),
        ],
    ),
    OccupationSpec(
        id=124,
        name="神职人员(犹太教拉比)",
        credit_min=9,
        credit_max=60,
        skill_points_formula="EDU*4",
        description="《克苏鲁的呼唤调查员伴侣》职业，使用前请征得KP同意。",
        skill_ids=["history", "language-native", "library-use", "occult", "psychology"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="一项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=None,
                label="任意一项其他技能",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "language-foreign-1",
                    "language-foreign-2",
                    "language-foreign-3",
                ],
                label="外语（任一）",
            ),
        ],
    ),
    OccupationSpec(
        id=125,
        name="专栏作家",
        credit_min=30,
        credit_max=70,
        skill_points_formula="EDU*4",
        description="《克苏鲁的呼唤调查员伴侣》职业，使用前请征得KP同意。",
        skill_ids=["disguise", "language-native", "psychology", "stealth"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="一项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["history", "library-use"],
                label="历史或图书馆（二选一）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "language-foreign-1",
                    "language-foreign-2",
                    "language-foreign-3",
                ],
                label="外语（任一）",
            ),
        ],
    ),
    OccupationSpec(
        id=126,
        name="社会主义者/激进主义者",
        credit_min=0,
        credit_max=30,
        skill_points_formula="EDU*2+MAX(APP,POW)*2",
        description="《克苏鲁的呼唤调查员伴侣》职业，使用前请征得KP同意。",
        skill_ids=["fighting-brawl", "firearm-handgun", "psychology"],
        choice_slots=[
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="两项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=None,
                label="任意两项其他个人或时代特长",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "language-foreign-1",
                    "language-foreign-2",
                    "language-foreign-3",
                ],
                label="外语（任一）",
            ),
        ],
    ),
    OccupationSpec(
        id=127,
        name="撰稿人",
        credit_min=20,
        credit_max=60,
        skill_points_formula="EDU*4",
        description="《克苏鲁的呼唤调查员伴侣》职业，使用前请征得KP同意。",
        skill_ids=["history", "language-native", "library-use", "listen", "psychology"],
        choice_slots=[
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="两项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["art-craft-1", "art-craft-2", "art-craft-3"],
                label="艺术（文学）",
            ),
        ],
    ),
    OccupationSpec(
        id=128,
        name="罪犯（赌博庄家）",
        credit_min=50,
        credit_max=80,
        skill_points_formula="EDU*2+MAX(DEX,APP)*2",
        description="《克苏鲁的呼唤调查员伴侣》职业，使用前请征得KP同意。",
        skill_ids=["accounting", "psychology", "sleight-of-hand", "spot-hidden"],
        choice_slots=[
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="两项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=None,
                label="任意一项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=129,
        name="罪犯（放高利贷者）",
        credit_min=50,
        credit_max=80,
        skill_points_formula="EDU*2+MAX(DEX,APP)*2",
        description="《克苏鲁的呼唤调查员伴侣》职业，使用前请征得KP同意。",
        skill_ids=["accounting", "appraise", "psychology", "spot-hidden"],
        choice_slots=[
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="两项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=None,
                label="任意两项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=130,
        name="罪犯（扒手）",
        credit_min=9,
        credit_max=30,
        skill_points_formula="EDU*2+DEX*2",
        description="《克苏鲁的呼唤调查员伴侣》职业，使用前请征得KP同意。",
        skill_ids=["disguise", "listen", "psychology", "sleight-of-hand", "spot-hidden", "stealth"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="一项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=None,
                label="任意一项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=131,
        name="罪犯（地下钱庄）",
        credit_min=30,
        credit_max=70,
        skill_points_formula="EDU*4",
        description="《克苏鲁的呼唤调查员伴侣》职业，使用前请征得KP同意。",
        skill_ids=["accounting", "law", "library-use", "listen", "persuade", "spot-hidden"],
        choice_slots=[
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=None,
                label="任意其他两项个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=132,
        name="罪犯（黑律师）",
        credit_min=30,
        credit_max=80,
        skill_points_formula="EDU*4",
        description="《克苏鲁的呼唤调查员伴侣》职业，使用前请征得KP同意。",
        skill_ids=["accounting", "law", "library-use", "psychology"],
        choice_slots=[
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="两项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=None,
                label="两项其他技能",
            ),
        ],
    ),
    OccupationSpec(
        id=133,
        name="牙医",
        credit_min=30,
        credit_max=70,
        skill_points_formula="EDU*4",
        description="《克苏鲁的呼唤调查员伴侣》职业，使用前请征得KP同意。",
        skill_ids=["first-aid", "medicine", "psychology", "science-biology", "science-pharmacy"],
        choice_slots=[
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=None,
                label="任两种其他学术或个人特长",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "language-foreign-1",
                    "language-foreign-2",
                    "language-foreign-3",
                ],
                label="外语（任一）",
            ),
        ],
    ),
    OccupationSpec(
        id=134,
        name="外科医生/内科医生",
        credit_min=50,
        credit_max=80,
        skill_points_formula="EDU*4",
        description="《克苏鲁的呼唤调查员伴侣》职业，使用前请征得KP同意。",
        skill_ids=["first-aid", "medicine", "psychology", "science-biology", "science-pharmacy"],
        choice_slots=[
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=None,
                label="任两种其他学术或个人特长",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "language-foreign-1",
                    "language-foreign-2",
                    "language-foreign-3",
                ],
                label="外语（任一）",
            ),
        ],
    ),
    OccupationSpec(
        id=135,
        name="整形医生",
        credit_min=30,
        credit_max=80,
        skill_points_formula="EDU*4",
        description="《克苏鲁的呼唤调查员伴侣》职业，使用前请征得KP同意。",
        skill_ids=["first-aid", "medicine", "psychology", "science-biology", "science-pharmacy"],
        choice_slots=[
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=None,
                label="任两种其他学术或个人特长",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "language-foreign-1",
                    "language-foreign-2",
                    "language-foreign-3",
                ],
                label="外语（任一）",
            ),
        ],
    ),
    OccupationSpec(
        id=136,
        name="司机-公交司机",
        credit_min=30,
        credit_max=50,
        skill_points_formula="EDU*2+DEX*2",
        description="《克苏鲁的呼唤调查员伴侣》职业，使用前请征得KP同意。",
        skill_ids=[
            "accounting",
            "drive-auto",
            "electrical-repair",
            "mechanical-repair",
            "navigation",
            "psychology",
        ],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="一项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=None,
                label="任意一项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=137,
        name="实地调研员",
        credit_min=9,
        credit_max=30,
        skill_points_formula="EDU*4",
        description="《克苏鲁的呼唤调查员伴侣》职业，使用前请征得KP同意。",
        skill_ids=["accounting", "first-aid", "library-use"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["climb", "jump"],
                label="攀爬或跳跃（二选一）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "language-foreign-1",
                    "language-foreign-2",
                    "language-foreign-3",
                ],
                label="外语（任一）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="一项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=None,
                label="两项研究领域相关技能",
            ),
        ],
    ),
    OccupationSpec(
        id=138,
        name="电影摄制人员",
        credit_min=9,
        credit_max=30,
        skill_points_formula="EDU*2+MAX(POW,DEX)*2",
        description="《克苏鲁的呼唤调查员伴侣》职业，使用前请征得KP同意。",
        skill_ids=["climb", "drive-auto", "electrical-repair", "mechanical-repair"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["art-craft-1", "art-craft-2", "art-craft-3"],
                label="艺术/工艺（任一，如摄影）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="一项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=None,
                label="任意两项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=139,
        name="司法科学家",
        credit_min=30,
        credit_max=50,
        skill_points_formula="EDU*4",
        description="《克苏鲁的呼唤调查员伴侣》职业，使用前请征得KP同意。",
        skill_ids=[
            "law",
            "medicine",
            "photography",
            "science-chemistry",
            "science-forensics",
            "science-pharmacy",
            "spot-hidden",
        ],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=None,
                label="任意一项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=140,
        name="运动经理",
        credit_min=20,
        credit_max=70,
        skill_points_formula="EDU*2+MAX(STR,DEX)*2",
        description="《克苏鲁的呼唤调查员伴侣》职业，使用前请征得KP同意。",
        skill_ids=["accounting", "dodge", "fighting-brawl", "first-aid", "psychology"],
        choice_slots=[
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="两项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=None,
                label="任意一项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=141,
        name="商船队船员",
        credit_min=20,
        credit_max=30,
        skill_points_formula="EDU*2+MAX(STR,DEX)*2",
        description="《克苏鲁的呼唤调查员伴侣》职业，使用前请征得KP同意。",
        skill_ids=["anthropology", "climb", "heavy-machinery", "jump", "survival"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["electrical-repair", "mechanical-repair"],
                label="电气维修或机械维修（二选一）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "language-foreign-1",
                    "language-foreign-2",
                    "language-foreign-3",
                ],
                label="外语（任一）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=None,
                label="任意一项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=142,
        name="古典音乐家",
        credit_min=9,
        credit_max=30,
        skill_points_formula="EDU*2+MAX(POW,DEX)*2",
        description="《克苏鲁的呼唤调查员伴侣》职业，使用前请征得KP同意。",
        skill_ids=["accounting", "listen", "psychology"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="一项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=3,
                candidate_skill_ids=None,
                label="三项其他技能",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["art-craft-1", "art-craft-2", "art-craft-3"],
                label="技艺（任一）",
            ),
        ],
    ),
    OccupationSpec(
        id=143,
        name="赛车手/ 赛艇手",
        credit_min=30,
        credit_max=70,
        skill_points_formula="EDU*2+DEX*2",
        description="《克苏鲁的呼唤调查员伴侣》职业，使用前请征得KP同意。",
        skill_ids=[
            "drive-auto",
            "electrical-repair",
            "mechanical-repair",
            "pilot-boat",
            "psychology",
            "spot-hidden",
        ],
        choice_slots=[
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=None,
                label="任意两项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=144,
        name="电台播音员",
        credit_min=50,
        credit_max=80,
        skill_points_formula="EDU*4",
        description="《克苏鲁的呼唤调查员伴侣》职业，使用前请征得KP同意。",
        skill_ids=["charm", "fast-talk", "language-native", "persuade", "psychology"],
        choice_slots=[
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=None,
                label="任意两项其他个人或时代特长",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["art-craft-1", "art-craft-2", "art-craft-3"],
                label="技艺（任一）",
            ),
        ],
    ),
    OccupationSpec(
        id=145,
        name="推销员（圣经推销员）",
        credit_min=9,
        credit_max=40,
        skill_points_formula="EDU*2+APP*2",
        description="《克苏鲁的呼唤调查员伴侣》职业，使用前请征得KP同意。",
        skill_ids=["accounting", "drive-auto", "listen", "psychology"],
        choice_slots=[
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="两项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["stealth", "sleight-of-hand"],
                label="潜行或妙手",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=None,
                label="一项其他技能",
            ),
        ],
    ),
    OccupationSpec(
        id=146,
        name="推销员（旅行推销员）",
        credit_min=9,
        credit_max=30,
        skill_points_formula="EDU*2+APP*2",
        description="《克苏鲁的呼唤调查员伴侣》职业，使用前请征得KP同意。",
        skill_ids=["accounting", "drive-auto", "listen", "navigation", "psychology"],
        choice_slots=[
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="两项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=None,
                label="一项其他技能",
            ),
        ],
    ),
    OccupationSpec(
        id=147,
        name="小企业家",
        credit_min=50,
        credit_max=70,
        skill_points_formula="EDU*4",
        description="《克苏鲁的呼唤调查员伴侣》职业，使用前请征得KP同意。",
        skill_ids=["accounting", "psychology"],
        choice_slots=[
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="两项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=4,
                candidate_skill_ids=None,
                label="四项经营业务相关技能",
            ),
        ],
    ),
    OccupationSpec(
        id=148,
        name="舞台工作人员",
        credit_min=9,
        credit_max=20,
        skill_points_formula="EDU*2+MAX(STR,DEX)*2",
        description="《克苏鲁的呼唤调查员伴侣》职业，使用前请征得KP同意。",
        skill_ids=["disguise", "language-native", "psychology"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["art-craft-1", "art-craft-2", "art-craft-3"],
                label="艺术/工艺（任一）",
            ),
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="两项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=None,
                label="任意两项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=149,
        name="证券经纪人",
        credit_min=60,
        credit_max=90,
        skill_points_formula="EDU*4",
        description="《克苏鲁的呼唤调查员伴侣》职业，使用前请征得KP同意。",
        skill_ids=["accounting", "appraise", "language-native", "psychology"],
        choice_slots=[
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="两项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=None,
                label="任意两项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=150,
        name="勘测员",
        credit_min=20,
        credit_max=60,
        skill_points_formula="EDU*4",
        description="《克苏鲁的呼唤调查员伴侣》职业，使用前请征得KP同意。",
        skill_ids=[
            "accounting",
            "library-use",
            "natural-world",
            "navigation",
            "photography",
            "spot-hidden",
            "survival",
        ],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=None,
                label="任意一项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=151,
        name="电话接线员",
        credit_min=20,
        credit_max=50,
        skill_points_formula="EDU*4",
        description="《克苏鲁的呼唤调查员伴侣》职业，使用前请征得KP同意。",
        skill_ids=["language-native", "listen", "psychology"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "language-foreign-1",
                    "language-foreign-2",
                    "language-foreign-3",
                ],
                label="外语",
            ),
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="两项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=None,
                label="任意两项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=152,
        name="星探",
        credit_min=9,
        credit_max=30,
        skill_points_formula="EDU*4",
        description="《克苏鲁的呼唤调查员伴侣》职业，使用前请征得KP同意。",
        skill_ids=["accounting", "law", "psychology", "spot-hidden"],
        choice_slots=[
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="两项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=None,
                label="任意两项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=153,
        name="医疗技术员",
        credit_min=30,
        credit_max=60,
        skill_points_formula="EDU*4",
        description="《克苏鲁的呼唤调查员伴侣》职业，使用前请征得KP同意。",
        skill_ids=[
            "electrical-repair",
            "library-use",
            "mechanical-repair",
            "medicine",
            "photography",
            "science-biology",
            "science-chemistry",
            "science-pharmacy",
        ],
    ),
    OccupationSpec(
        id=154,
        name="队医",
        credit_min=9,
        credit_max=30,
        skill_points_formula="EDU*4",
        description="《克苏鲁的呼唤调查员伴侣》职业，使用前请征得KP同意。",
        skill_ids=["first-aid", "medicine", "psychology", "science-pharmacy", "spot-hidden"],
        choice_slots=[
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="两项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=None,
                label="任意一项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=155,
        name="寻宝猎人",
        credit_min=9,
        credit_max=30,
        skill_points_formula="EDU*2+MAX(STR,DEX)*2",
        description="《克苏鲁的呼唤调查员伴侣》职业，使用前请征得KP同意。",
        skill_ids=["appraise", "climb", "history", "jump", "spot-hidden"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["drive-auto", "pilot-aircraft", "pilot-boat"],
                label="汽车驾驶或驾驶（飞行器或船）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["electrical-repair", "mechanical-repair"],
                label="电气维修或机械维修",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="一项社交技能（取悦、话术、恐吓、说服）",
            ),
        ],
    ),
    OccupationSpec(
        id=156,
        name="西部治安官",
        credit_min=20,
        credit_max=50,
        skill_points_formula="EDU*2+MAX(STR,DEX)*2",
        description="《日本秘史》职业，使用前请征得KP同意。",
        skill_ids=["drive-auto", "fighting-brawl", "fighting-whip", "law", "ride", "track"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "firearm-handgun",
                    "firearm-rifle",
                    "firearm-smg",
                    "firearm-machine-gun",
                    "firearm-bow",
                    "firearm-flamethrower",
                ],
                label="射击（任一）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["persuade", "psychology"],
                label="说服或心理学",
            ),
        ],
    ),
    OccupationSpec(
        id=157,
        name="暴走族",
        credit_min=5,
        credit_max=10,
        skill_points_formula="EDU*2+MAX(STR,DEX)*2",
        description="《日本秘史》职业，使用前请征得KP同意。",
        skill_ids=["drive-auto", "fast-talk", "fighting-brawl", "intimidate", "mechanical-repair"],
        choice_slots=[
            SkillChoiceSlot(
                count=3,
                candidate_skill_ids=None,
                label="任意三项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=158,
        name="神职人员(和尚,尼姑)",
        credit_min=5,
        credit_max=60,
        skill_points_formula="EDU*4",
        description="《日本秘史》职业，使用前请征得KP同意。",
        skill_ids=["listen", "psychology"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["art-craft-1", "art-craft-2", "art-craft-3"],
                label="艺术（书法）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["history", "library-use"],
                label="历史或图书馆",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "language-foreign-1",
                    "language-foreign-2",
                    "language-foreign-3",
                ],
                label="外语（汉语或梵语）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="一项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=None,
                label="任意一项其他个人或时代特长",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["lore-1", "lore-2", "lore-3"],
                label="学识（佛教）",
            ),
        ],
    ),
    OccupationSpec(
        id=159,
        name="神职人员(神官,巫女)",
        credit_min=20,
        credit_max=60,
        skill_points_formula="EDU*4",
        description="《日本秘史》职业，使用前请征得KP同意。",
        skill_ids=["library-use", "occult", "psychology"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["art-craft-1", "art-craft-2", "art-craft-3"],
                label="艺术（书法）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="一项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=None,
                label="任意一项其他个人或时代特长",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["lore-1", "lore-2", "lore-3"],
                label="学识（神道教）",
            ),
        ],
    ),
    OccupationSpec(
        id=160,
        name="风水师",
        credit_min=20,
        credit_max=50,
        skill_points_formula="EDU*4",
        description="《日本秘史》职业，使用前请征得KP同意。",
        skill_ids=["library-use", "occult", "science-astronomy", "science-geology"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["art-craft-1", "art-craft-2", "art-craft-3"],
                label="艺术（任一）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="一项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=None,
                label="任意一项其他个人或时代特长",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["lore-1", "lore-2", "lore-3"],
                label="学识（道教）",
            ),
        ],
    ),
    OccupationSpec(
        id=161,
        name="家传降妖人",
        credit_min=9,
        credit_max=20,
        skill_points_formula="EDU*2+MAX(STR,DEX)*2",
        description="《日本秘史》职业，使用前请征得KP同意。",
        skill_ids=["fighting-brawl", "natural-world", "occult", "psychology", "stealth"],
        choice_slots=[
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=None,
                label="任意两项其他个人或时代特长",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["lore-1", "lore-2", "lore-3"],
                label="学识（佛教或神道教）",
            ),
        ],
    ),
    OccupationSpec(
        id=162,
        name="高中生(教育60以下)",
        credit_min=5,
        credit_max=10,
        skill_points_formula="EDU*4",
        description="《日本秘史》职业，使用前请征得KP同意。",
        skill_ids=["climb", "jump", "language-native", "library-use", "stealth"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "fighting-brawl",
                    "fighting-sword",
                    "fighting-axe",
                    "fighting-spear",
                    "fighting-whip",
                    "fighting-chain",
                    "fighting-knife",
                ],
                label="格斗（任一）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "science-pharmacy",
                    "science-biology",
                    "science-chemistry",
                    "science-physics",
                    "science-geology",
                    "science-astronomy",
                    "science-forensics",
                    "science-mathematics",
                    "science-engineering",
                    "science-botany",
                    "science-zoology",
                    "science-cryptography",
                    "science-metallurgy",
                    "science-meteorology",
                    "history",
                ],
                label="科学（任一）或历史",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "language-foreign-1",
                    "language-foreign-2",
                    "language-foreign-3",
                ],
                label="外语（任一）",
            ),
        ],
    ),
    OccupationSpec(
        id=163,
        name="市子（盲人）",
        credit_min=5,
        credit_max=30,
        skill_points_formula="EDU*4",
        description="《日本秘史》职业，使用前请征得KP同意。",
        skill_ids=["history", "listen", "occult", "psychology"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["fast-talk", "persuade"],
                label="话术或说服",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=None,
                label="任意一项特长（经KP同意可用「灵媒」技能代替）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["lore-1", "lore-2", "lore-3"],
                label="学识（神道教）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["art-craft-1", "art-craft-2", "art-craft-3"],
                label="技艺（任一）",
            ),
        ],
    ),
    OccupationSpec(
        id=164,
        name="言灵师/阴阳师",
        credit_min=9,
        credit_max=20,
        skill_points_formula="EDU*4",
        description="《日本秘史》职业，使用前请征得KP同意。",
        skill_ids=["language-native", "occult", "science-astronomy"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["art-craft-1", "art-craft-2", "art-craft-3"],
                label="艺术与手艺（另任一）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["history", "library-use"],
                label="历史或图书馆",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=None,
                label="任意一项其他个人或时代特长",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["lore-1", "lore-2", "lore-3"],
                label="学识（阴阳道）",
            ),
        ],
    ),
    OccupationSpec(
        id=165,
        name="炼丹师",
        credit_min=30,
        credit_max=50,
        skill_points_formula="EDU*4",
        description="《日本秘史》职业，使用前请征得KP同意。",
        skill_ids=["library-use", "medicine", "natural-world", "occult", "science-chemistry"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "language-foreign-1",
                    "language-foreign-2",
                    "language-foreign-3",
                ],
                label="外语（汉语）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["first-aid", "psychoanalysis"],
                label="急救或精神分析",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["lore-1", "lore-2", "lore-3"],
                label="学识（道教）",
            ),
        ],
    ),
    OccupationSpec(
        id=166,
        name="外语教师",
        credit_min=30,
        credit_max=60,
        skill_points_formula="EDU*4",
        description="《日本秘史》职业，使用前请征得KP同意。",
        skill_ids=["history", "language-native", "listen", "psychology"],
        choice_slots=[
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="两项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=None,
                label="任意两项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=167,
        name="非法移民",
        credit_min=0,
        credit_max=5,
        skill_points_formula="EDU*2+MAX(STR,DEX)*2",
        description="《日本秘史》职业，使用前请征得KP同意。",
        skill_ids=[
            "disguise",
            "fast-talk",
            "listen",
            "psychology",
            "sleight-of-hand",
            "spot-hidden",
            "stealth",
        ],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=None,
                label="任意一项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=168,
        name="相扑力士(SIZ>80,STR>70)",
        credit_min=9,
        credit_max=60,
        skill_points_formula="EDU*2+STR*2",
        description="《日本秘史》职业，使用前请征得KP同意。",
        skill_ids=["dodge", "fighting-brawl", "intimidate", "jump", "psychology", "spot-hidden"],
        choice_slots=[
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=None,
                label="任意两项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=169,
        name="渔民",
        credit_min=9,
        credit_max=30,
        skill_points_formula="EDU*2+MAX(STR,DEX)*2",
        description="日系特定规则《克苏鲁2010》职业，使用前请征得KP同意。",
        skill_ids=[
            "heavy-machinery",
            "mechanical-repair",
            "natural-world",
            "navigation",
            "pilot-boat",
            "science-astronomy",
            "spot-hidden",
            "swim",
        ],
    ),
    OccupationSpec(
        id=170,
        name="心理治疗师",
        credit_min=30,
        credit_max=50,
        skill_points_formula="EDU*4",
        description="日系特定规则《克苏鲁2010》职业，使用前请征得KP同意。",
        skill_ids=["law", "psychoanalysis", "psychology"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["art-craft-1", "art-craft-2", "art-craft-3"],
                label="艺术（任一）",
            ),
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="两项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "language-foreign-1",
                    "language-foreign-2",
                    "language-foreign-3",
                ],
                label="外语（任一）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=None,
                label="任意一项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=171,
        name="女学生",
        credit_min=5,
        credit_max=10,
        skill_points_formula="EDU*4",
        description="日系特定规则《克苏鲁与帝国》职业，使用前请征得KP同意。",
        skill_ids=["first-aid", "library-use", "listen"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="一项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["art-craft-1", "art-craft-2", "art-craft-3"],
                label="艺术/工艺（任一）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["fighting-spear", "firearm-bow"],
                label="格斗（矛）或射击（弓术）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "language-foreign-1",
                    "language-foreign-2",
                    "language-foreign-3",
                ],
                label="外语（任一）",
            ),
        ],
    ),
    OccupationSpec(
        id=172,
        name="寄居学生",
        credit_min=5,
        credit_max=10,
        skill_points_formula="EDU*4",
        description="日系特定规则《克苏鲁与帝国》职业，使用前请征得KP同意。",
        skill_ids=["accounting", "carpentry", "first-aid", "library-use", "persuade"],
        choice_slots=[
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=None,
                label="任意两项其他个人或时代特长",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "language-foreign-1",
                    "language-foreign-2",
                    "language-foreign-3",
                ],
                label="外语（任一）",
            ),
        ],
    ),
    OccupationSpec(
        id=173,
        name="动物辅助治疗师",
        credit_min=30,
        credit_max=50,
        skill_points_formula="EDU*2+MAX(APP,POW)*2",
        description="日系特定规则《克苏鲁2015》职业，使用前请征得KP同意。",
        skill_ids=[
            "jump",
            "listen",
            "natural-world",
            "psychoanalysis",
            "psychology",
            "science-zoology",
            "track",
        ],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=None,
                label="任意一项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=174,
        name="急诊医生/救援队员",
        credit_min=10,
        credit_max=50,
        skill_points_formula="EDU*4",
        description="日系特定规则《克苏鲁2015》职业，使用前请征得KP同意。",
        skill_ids=[
            "climb",
            "electrical-repair",
            "first-aid",
            "jump",
            "lock-smith",
            "mechanical-repair",
            "medicine",
            "science-chemistry",
        ],
    ),
    OccupationSpec(
        id=175,
        name="密医",
        credit_min=10,
        credit_max=70,
        skill_points_formula="EDU*4",
        description="日系特定规则《克苏鲁2015》职业，使用前请征得KP同意。",
        skill_ids=["accounting", "first-aid", "law", "medicine", "science-pharmacy"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="一项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=None,
                label="任意一项其他个人或时代特长",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "language-foreign-1",
                    "language-foreign-2",
                    "language-foreign-3",
                ],
                label="外语（任一）",
            ),
        ],
    ),
    OccupationSpec(
        id=176,
        name="科学搜查研究员",
        credit_min=30,
        credit_max=50,
        skill_points_formula="EDU*4",
        description="日系特定规则《克苏鲁2015》职业，使用前请征得KP同意。",
        skill_ids=[
            "law",
            "medicine",
            "photography",
            "science-chemistry",
            "science-forensics",
            "science-pharmacy",
            "spot-hidden",
        ],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=None,
                label="任意一项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=177,
        name="山岳救援队员",
        credit_min=10,
        credit_max=50,
        skill_points_formula="EDU*2+MAX(STR,DEX)*2",
        description="日系特定规则《克苏鲁2015》职业，使用前请征得KP同意。",
        skill_ids=["climb", "first-aid", "jump", "listen", "navigation", "survival", "track"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "language-foreign-1",
                    "language-foreign-2",
                    "language-foreign-3",
                ],
                label="外语（任选一门）",
            ),
        ],
    ),
    OccupationSpec(
        id=178,
        name="舞者",
        credit_min=9,
        credit_max=70,
        skill_points_formula="EDU*2+APP*2",
        description="日系特定规则《克苏鲁2015》职业，使用前请征得KP同意。",
        skill_ids=["disguise", "listen", "psychology"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["art-craft-1", "art-craft-2", "art-craft-3"],
                label="技艺（表演类，如表演、演唱、喜剧等）",
            ),
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="两项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=None,
                label="任意两项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=179,
        name="服装设计师",
        credit_min=20,
        credit_max=60,
        skill_points_formula="EDU*4",
        description="日系特定规则《克苏鲁2015》职业，使用前请征得KP同意。",
        skill_ids=["accounting", "disguise", "photography", "psychology", "spot-hidden"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["art-craft-1", "art-craft-2", "art-craft-3"],
                label="技艺（任一）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["computer-use", "library-use"],
                label="计算机使用或图书馆使用（二选一）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=None,
                label="任意一项其他个人特长",
            ),
        ],
    ),
    OccupationSpec(
        id=180,
        name="海上自卫队员",
        credit_min=9,
        credit_max=30,
        skill_points_formula="EDU*4",
        description="日系特定规则《克苏鲁2015》职业，使用前请征得KP同意。",
        skill_ids=["first-aid", "navigation", "pilot-boat", "survival", "swim"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["electrical-repair", "mechanical-repair"],
                label="电气维修或机械维修（二选一）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "fighting-brawl",
                    "fighting-sword",
                    "fighting-axe",
                    "fighting-spear",
                    "fighting-whip",
                    "fighting-chain",
                    "fighting-knife",
                ],
                label="格斗（任选一种专精）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "firearm-handgun",
                    "firearm-rifle",
                    "firearm-smg",
                    "firearm-machine-gun",
                    "firearm-bow",
                    "firearm-flamethrower",
                ],
                label="射击（任选一种专精）",
            ),
        ],
    ),
    OccupationSpec(
        id=181,
        name="海警",
        credit_min=20,
        credit_max=40,
        skill_points_formula="EDU*4",
        description="日系特定规则《克苏鲁2015》职业，使用前请征得KP同意。",
        skill_ids=[
            "first-aid",
            "mechanical-repair",
            "natural-world",
            "navigation",
            "pilot-boat",
            "spot-hidden",
            "swim",
        ],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="一项社交技能（取悦、话术、恐吓、说服）",
            ),
        ],
    ),
    OccupationSpec(
        id=182,
        name="陆上自卫队员",
        credit_min=9,
        credit_max=30,
        skill_points_formula="EDU*2+MAX(STR,DEX)*2",
        description="日系特定规则《克苏鲁2015》职业，使用前请征得KP同意。",
        skill_ids=["dodge", "stealth", "survival"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["climb", "swim"],
                label="攀爬或游泳（二选一）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "fighting-brawl",
                    "fighting-sword",
                    "fighting-axe",
                    "fighting-spear",
                    "fighting-whip",
                    "fighting-chain",
                    "fighting-knife",
                ],
                label="格斗（任选一种专精）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "firearm-handgun",
                    "firearm-rifle",
                    "firearm-smg",
                    "firearm-machine-gun",
                    "firearm-bow",
                    "firearm-flamethrower",
                ],
                label="射击（任选一种专精）",
            ),
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=[
                    "language-foreign-1",
                    "language-foreign-2",
                    "language-foreign-3",
                ],
                label="下面任选两项：急救、机械维修、外语",
            ),
        ],
    ),
    OccupationSpec(
        id=183,
        name="私人军事公司成员",
        credit_min=9,
        credit_max=30,
        skill_points_formula="EDU*2+MAX(STR,DEX)*2",
        description="日系特定规则《克苏鲁2015》职业，使用前请征得KP同意。",
        skill_ids=["dodge", "stealth", "survival"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["climb", "swim"],
                label="攀爬或游泳（二选一）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "fighting-brawl",
                    "fighting-sword",
                    "fighting-axe",
                    "fighting-spear",
                    "fighting-whip",
                    "fighting-chain",
                    "fighting-knife",
                ],
                label="格斗（任选一种专精）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "firearm-handgun",
                    "firearm-rifle",
                    "firearm-smg",
                    "firearm-machine-gun",
                    "firearm-bow",
                    "firearm-flamethrower",
                ],
                label="射击（任选一种专精）",
            ),
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=[
                    "language-foreign-1",
                    "language-foreign-2",
                    "language-foreign-3",
                ],
                label="下面任选两项：急救、机械维修、外语",
            ),
        ],
    ),
    OccupationSpec(
        id=184,
        name="冒险家教授",
        credit_min=55,
        credit_max=80,
        skill_points_formula="EDU*2+MAX(APP,DEX,STR)*2",
        description="日系特定规则《克苏鲁2015》职业，使用前请征得KP同意。",
        skill_ids=["history", "jump", "natural-world", "navigation", "survival"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["climb", "swim"],
                label="攀爬或游泳（二选一）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "firearm-handgun",
                    "firearm-rifle",
                    "firearm-smg",
                    "firearm-machine-gun",
                    "firearm-bow",
                    "firearm-flamethrower",
                ],
                label="射击（任选一种专精）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "language-foreign-1",
                    "language-foreign-2",
                    "language-foreign-3",
                ],
                label="外语（任选一门）",
            ),
        ],
    ),
    OccupationSpec(
        id=185,
        name="评论家",
        credit_min=30,
        credit_max=70,
        skill_points_formula="EDU*4",
        description="日系特定规则《克苏鲁2015》职业，使用前请征得KP同意。",
        skill_ids=["disguise", "language-native", "psychology", "stealth"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="一项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["history", "library-use"],
                label="历史或图书馆使用（二选一）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "language-foreign-1",
                    "language-foreign-2",
                    "language-foreign-3",
                ],
                label="外语（任选一门）",
            ),
        ],
    ),
    OccupationSpec(
        id=186,
        name="偶像",
        credit_min=9,
        credit_max=70,
        skill_points_formula="EDU*2+APP*2",
        description="日系特定规则《克苏鲁2015》职业，使用前请征得KP同意。",
        skill_ids=["disguise", "listen", "psychology"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["art-craft-1", "art-craft-2", "art-craft-3"],
                label="技艺（表演、歌唱、舞蹈中任选其一）",
            ),
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="两项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=None,
                label="任意两项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=187,
        name="歌手",
        credit_min=9,
        credit_max=70,
        skill_points_formula="EDU*2+APP*2",
        description="日系特定规则《克苏鲁2015》职业，使用前请征得KP同意。",
        skill_ids=["disguise", "listen", "psychology"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["art-craft-1", "art-craft-2", "art-craft-3"],
                label="技艺（歌唱、舞蹈、乐器中任选其一）",
            ),
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="两项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=None,
                label="任意两项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=188,
        name="搞笑艺人",
        credit_min=9,
        credit_max=70,
        skill_points_formula="EDU*2+APP*2",
        description="日系特定规则《克苏鲁2015》职业，使用前请征得KP同意。",
        skill_ids=["disguise", "listen", "psychology"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["art-craft-1", "art-craft-2", "art-craft-3"],
                label="技艺（表演、杂技、喜剧中任选其一）",
            ),
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="两项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=None,
                label="任意两项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=189,
        name="运动员艺人",
        credit_min=9,
        credit_max=20,
        skill_points_formula="EDU*2+DEX*2",
        description="日系特定规则《克苏鲁2015》职业，使用前请征得KP同意。",
        skill_ids=["climb", "dodge", "jump", "spot-hidden", "swim", "throw"],
        choice_slots=[
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=None,
                label="任意两项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=190,
        name="播音员",
        credit_min=50,
        credit_max=80,
        skill_points_formula="EDU*4",
        description="日系特定规则《克苏鲁2015》职业，使用前请征得KP同意。",
        skill_ids=["charm", "fast-talk", "language-native", "persuade", "psychology"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["art-craft-1", "art-craft-2", "art-craft-3"],
                label="艺术（表演）",
            ),
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=None,
                label="任意两项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=191,
        name="主持人",
        credit_min=50,
        credit_max=80,
        skill_points_formula="EDU*4",
        description="日系特定规则《克苏鲁2015》职业，使用前请征得KP同意。",
        skill_ids=["charm", "fast-talk", "language-native", "persuade", "psychology"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["art-craft-1", "art-craft-2", "art-craft-3"],
                label="艺术（表演）",
            ),
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=None,
                label="任意两项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=192,
        name="电视解说员",
        credit_min=50,
        credit_max=80,
        skill_points_formula="EDU*4",
        description="日系特定规则《克苏鲁2015》职业，使用前请征得KP同意。",
        skill_ids=["charm", "fast-talk", "language-native", "persuade", "psychology"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["art-craft-1", "art-craft-2", "art-craft-3"],
                label="艺术（表演）",
            ),
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=None,
                label="任意两项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=193,
        name="网络明星",
        credit_min=9,
        credit_max=70,
        skill_points_formula="EDU*2+APP*2",
        description="日系特定规则《克苏鲁2015》职业，使用前请征得KP同意。",
        skill_ids=["computer-use", "disguise", "electrical-repair", "listen", "psychology"],
        choice_slots=[
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="两项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["art-craft-1", "art-craft-2", "art-craft-3"],
                label="技艺（任一）",
            ),
        ],
    ),
    OccupationSpec(
        id=194,
        name="经纪人",
        credit_min=30,
        credit_max=70,
        skill_points_formula="EDU*4",
        description="日系特定规则《克苏鲁2015》职业，使用前请征得KP同意。",
        skill_ids=["drive-auto", "law", "listen", "stealth"],
        choice_slots=[
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="两项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=None,
                label="任意两项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=195,
        name="捉鬼人",
        credit_min=9,
        credit_max=30,
        skill_points_formula="EDU*2+DEX*2",
        description="日系特定规则《克苏鲁2015》职业，使用前请征得KP同意。",
        skill_ids=[
            "electrical-repair",
            "mechanical-repair",
            "occult",
            "photography",
            "science-biology",
            "science-chemistry",
            "science-physics",
        ],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="一项社交技能（取悦、话术、恐吓、说服）",
            ),
        ],
    ),
    OccupationSpec(
        id=196,
        name="占卜师、灵媒师",
        credit_min=9,
        credit_max=30,
        skill_points_formula="EDU*2+MAX(EDU,APP)*2",
        description="日系特定规则《克苏鲁2015》职业，使用前请征得KP同意。",
        skill_ids=["history", "library-use", "occult", "psychology"],
        choice_slots=[
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="两项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=None,
                label="任意一项其他个人或时代特长",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["art-craft-1", "art-craft-2", "art-craft-3"],
                label="技艺（任一）",
            ),
        ],
    ),
    OccupationSpec(
        id=197,
        name="机械师",
        credit_min=9,
        credit_max=40,
        skill_points_formula="EDU*4",
        description="日系特定规则《克苏鲁2015》职业，使用前请征得KP同意。",
        skill_ids=[
            "climb",
            "drive-auto",
            "electrical-repair",
            "heavy-machinery",
            "mechanical-repair",
        ],
        choice_slots=[
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=None,
                label="任意两项其他个人或时代或技术特长",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["art-craft-1", "art-craft-2", "art-craft-3"],
                label="技艺（任一）",
            ),
        ],
    ),
    OccupationSpec(
        id=198,
        name="厨师",
        credit_min=9,
        credit_max=30,
        skill_points_formula="EDU*2+DEX*2",
        description="日系特定规则《克苏鲁2015》职业，使用前请征得KP同意。",
        skill_ids=[
            "fighting-brawl",
            "natural-world",
            "science-biology",
            "science-chemistry",
            "spot-hidden",
        ],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=None,
                label="任意一项其他个人或时代特长",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["art-craft-1", "art-craft-2", "art-craft-3"],
                label="技艺（任一）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "language-foreign-1",
                    "language-foreign-2",
                    "language-foreign-3",
                ],
                label="外语（任一）",
            ),
        ],
    ),
    OccupationSpec(
        id=199,
        name="网络犯罪者",
        credit_min=10,
        credit_max=70,
        skill_points_formula="EDU*4",
        description="日系特定规则《克苏鲁2015》职业，使用前请征得KP同意。",
        skill_ids=[
            "computer-use",
            "electrical-repair",
            "electronics",
            "library-use",
            "spot-hidden",
        ],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="一项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=None,
                label="任意两项其他技能",
            ),
        ],
    ),
    OccupationSpec(
        id=200,
        name="佣兵",
        credit_min=9,
        credit_max=30,
        skill_points_formula="EDU*2+MAX(STR,DEX)*2",
        description="日系特定规则《克苏鲁2015》职业，使用前请征得KP同意。",
        skill_ids=["dodge", "stealth", "survival"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["climb", "swim"],
                label="攀爬或游泳",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "fighting-brawl",
                    "fighting-sword",
                    "fighting-axe",
                    "fighting-spear",
                    "fighting-whip",
                    "fighting-chain",
                    "fighting-knife",
                ],
                label="格斗（任一专精）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "firearm-handgun",
                    "firearm-rifle",
                    "firearm-smg",
                    "firearm-machine-gun",
                    "firearm-bow",
                    "firearm-flamethrower",
                ],
                label="射击（任一专精）",
            ),
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=[
                    "language-foreign-1",
                    "language-foreign-2",
                    "language-foreign-3",
                ],
                label="下面任选两项：急救、机械维修、外语",
            ),
        ],
    ),
    OccupationSpec(
        id=201,
        name="自宅警备员",
        credit_min=1,
        credit_max=10,
        skill_points_formula="EDU*4",
        description="日系特定规则《克苏鲁2015》职业，使用前请征得KP同意。",
        skill_ids=["computer-use", "language-native", "library-use", "listen", "stealth"],
        choice_slots=[
            SkillChoiceSlot(
                count=3,
                candidate_skill_ids=None,
                label="任意三项符合尼特族形象的特长",
            ),
        ],
    ),
    OccupationSpec(
        id=202,
        name="壮汉保镖",
        credit_min=9,
        credit_max=30,
        skill_points_formula="EDU*2+MAX(STR,DEX)*2",
        description="日系特定规则《克苏鲁2015》职业，使用前请征得KP同意。",
        skill_ids=["fighting-brawl", "first-aid", "law", "psychology", "spot-hidden"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "firearm-handgun",
                    "firearm-rifle",
                    "firearm-smg",
                    "firearm-machine-gun",
                    "firearm-bow",
                    "firearm-flamethrower",
                ],
                label="射击（任一专精）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="一项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["drive-auto", "ride"],
                label="下面的一种个人特长：汽车驾驶或骑术",
            ),
        ],
    ),
    OccupationSpec(
        id=203,
        name="游戏测试员",
        credit_min=9,
        credit_max=20,
        skill_points_formula="EDU*4",
        description="日系特定规则《克苏鲁2015》职业，使用前请征得KP同意。",
        skill_ids=["computer-use", "electrical-repair", "electronics", "listen"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="一项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=None,
                label="任意两项其他个人或时代特长",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["art-craft-1", "art-craft-2", "art-craft-3"],
                label="技艺（任一）",
            ),
        ],
    ),
    OccupationSpec(
        id=204,
        name="交际花",
        credit_min=9,
        credit_max=30,
        skill_points_formula="EDU*2+APP*2",
        description="《克苏鲁煤气灯》1980s职业，使用前请征得KP同意。",
        skill_ids=["appraise", "first-aid", "psychology", "ride", "stealth"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="一项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["disguise", "lock-smith"],
                label="（乔装、钳工）中的一种",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=None,
                label="任意一项其他个人或时代特长",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["art-craft-1", "art-craft-2", "art-craft-3"],
                label="技艺（任一）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "language-foreign-1",
                    "language-foreign-2",
                    "language-foreign-3",
                ],
                label="外语（任一）",
            ),
        ],
    ),
    OccupationSpec(
        id=205,
        name="考古学家",
        credit_min=30,
        credit_max=60,
        skill_points_formula="EDU*4",
        description="《克苏鲁煤气灯》1980s职业，使用前请征得KP同意。",
        skill_ids=["accounting", "appraise", "history", "library-use", "psychology", "spot-hidden"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="一项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=None,
                label="任意两项其他个人或时代特长",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["art-craft-1", "art-craft-2", "art-craft-3"],
                label="技艺（任一）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "language-foreign-1",
                    "language-foreign-2",
                    "language-foreign-3",
                ],
                label="外语（任一）",
            ),
        ],
    ),
    OccupationSpec(
        id=206,
        name="贵族",
        credit_min=70,
        credit_max=99,
        skill_points_formula="EDU*2+MAX(EDU,APP)*2",
        description="《克苏鲁煤气灯》1980s职业，使用前请征得KP同意。",
        skill_ids=["firearm-rifle", "law", "ride"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="一项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=3,
                candidate_skill_ids=None,
                label="任意三项其他个人或时代特长",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "language-foreign-1",
                    "language-foreign-2",
                    "language-foreign-3",
                ],
                label="外语（任一）",
            ),
        ],
    ),
    OccupationSpec(
        id=207,
        name="艺术家",
        credit_min=10,
        credit_max=40,
        skill_points_formula="EDU*2+MAX(DEX,POW)*2",
        description="《克苏鲁煤气灯》1980s职业，使用前请征得KP同意。",
        skill_ids=["appraise", "history", "library-use", "spot-hidden"],
        choice_slots=[
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=None,
                label="任意两项其他个人或时代特长",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["art-craft-1", "art-craft-2", "art-craft-3"],
                label="技艺（任一）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "language-foreign-1",
                    "language-foreign-2",
                    "language-foreign-3",
                ],
                label="外语（任一）",
            ),
        ],
    ),
    OccupationSpec(
        id=208,
        name="作家",
        credit_min=10,
        credit_max=40,
        skill_points_formula="EDU*4",
        description="《克苏鲁煤气灯》1980s职业，使用前请征得KP同意。",
        skill_ids=["history", "language-native", "library-use", "psychology"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="一项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=None,
                label="任意两项其他个人或时代特长",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["art-craft-1", "art-craft-2", "art-craft-3"],
                label="技艺（任一）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "language-foreign-1",
                    "language-foreign-2",
                    "language-foreign-3",
                ],
                label="外语（任一）",
            ),
        ],
    ),
    OccupationSpec(
        id=209,
        name="马车夫",
        credit_min=3,
        credit_max=10,
        skill_points_formula="EDU*2+DEX*2",
        description="《克苏鲁煤气灯》1980s职业，使用前请征得KP同意。",
        skill_ids=[
            "dodge",
            "drive-carriage",
            "fighting-whip",
            "jump",
            "listen",
            "mechanical-repair",
            "natural-world",
            "navigation",
            "spot-hidden",
        ],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="一项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=None,
                label="任意一项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=210,
        name="牧师",
        credit_min=20,
        credit_max=65,
        skill_points_formula="EDU*2+MAX(APP,POW)*2",
        description="《克苏鲁煤气灯》1980s职业，使用前请征得KP同意。",
        skill_ids=["history", "library-use", "psychology"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="一项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=None,
                label="任意两项其他个人或时代特长",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "language-foreign-1",
                    "language-foreign-2",
                    "language-foreign-3",
                ],
                label="外语（任一）",
            ),
        ],
    ),
    OccupationSpec(
        id=211,
        name="咨询侦探",
        credit_min=10,
        credit_max=60,
        skill_points_formula="EDU*4",
        description="《克苏鲁煤气灯》1980s职业，使用前请征得KP同意。",
        skill_ids=[
            "anthropology",
            "appraise",
            "first-aid",
            "history",
            "law",
            "library-use",
            "listen",
            "psychology",
            "science-chemistry",
            "spot-hidden",
            "track",
        ],
        choice_slots=[
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=None,
                label="任意两项其他个人或时代特长",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "language-foreign-1",
                    "language-foreign-2",
                    "language-foreign-3",
                ],
                label="外语（任一）",
            ),
        ],
    ),
    OccupationSpec(
        id=212,
        name="工匠",
        credit_min=9,
        credit_max=35,
        skill_points_formula="EDU*2+MAX(STR,DEX)*2",
        description="《克苏鲁煤气灯》1980s职业，使用前请征得KP同意。",
        skill_ids=["accounting", "appraise", "mechanical-repair", "spot-hidden"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="一项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=None,
                label="任意一项其他个人或时代特长",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["art-craft-1", "art-craft-2", "art-craft-3"],
                label="技艺（任一）",
            ),
        ],
    ),
    OccupationSpec(
        id=213,
        name="罪犯",
        credit_min=9,
        credit_max=30,
        skill_points_formula="EDU*2+MAX(APP,DEX,STR)*2",
        description="《克苏鲁煤气灯》1980s职业，使用前请征得KP同意。",
        skill_ids=["appraise", "disguise", "lock-smith", "stealth"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="一项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=[
                    "fighting-brawl",
                    "fighting-sword",
                    "fighting-axe",
                    "fighting-spear",
                    "fighting-whip",
                    "fighting-chain",
                    "fighting-knife",
                ],
                label="格斗（任意两项）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=None,
                label="任意一项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=214,
        name="业余艺术爱好者",
        credit_min=10,
        credit_max=70,
        skill_points_formula="EDU*2+APP*2",
        description="《克苏鲁煤气灯》1980s职业，使用前请征得KP同意。",
        skill_ids=[],
        choice_slots=[
            SkillChoiceSlot(
                count=6,
                candidate_skill_ids=None,
                label="任意六项个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=215,
        name="艺人",
        credit_min=10,
        credit_max=40,
        skill_points_formula="EDU*2+MAX(APP,POW)*2",
        description="《克苏鲁煤气灯》1980s职业，使用前请征得KP同意。",
        skill_ids=["disguise", "dodge", "language-native", "listen", "psychology"],
        choice_slots=[
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="两项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=3,
                candidate_skill_ids=None,
                label="任意三项其他个人或时代特长",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["art-craft-1", "art-craft-2", "art-craft-3"],
                label="技艺（任一）",
            ),
        ],
    ),
    OccupationSpec(
        id=216,
        name="退役军官",
        credit_min=40,
        credit_max=75,
        skill_points_formula="EDU*4",
        description="《克苏鲁煤气灯》1980s职业，使用前请征得KP同意。",
        skill_ids=[
            "fighting-sword",
            "firearm-handgun",
            "firearm-rifle",
            "first-aid",
            "navigation",
            "psychology",
            "ride",
            "spot-hidden",
            "stealth",
        ],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="一项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["climb", "swim"],
                label="（攀爬、游泳）中的一种",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "language-foreign-1",
                    "language-foreign-2",
                    "language-foreign-3",
                ],
                label="外语（任一）",
            ),
        ],
    ),
    OccupationSpec(
        id=217,
        name="探险家",
        credit_min=45,
        credit_max=70,
        skill_points_formula="EDU*2+MAX(APP,DEX,STR)*2",
        description="《克苏鲁煤气灯》1980s职业，使用前请征得KP同意。",
        skill_ids=[
            "anthropology",
            "appraise",
            "archaeology",
            "climb",
            "fighting-brawl",
            "firearm-handgun",
            "firearm-rifle",
            "first-aid",
            "natural-world",
            "navigation",
            "pilot-balloon",
            "pilot-boat",
            "ride",
            "science-biology",
            "spot-hidden",
            "stealth",
            "swim",
            "track",
        ],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "language-foreign-1",
                    "language-foreign-2",
                    "language-foreign-3",
                ],
                label="外语（任一）",
            ),
        ],
    ),
    OccupationSpec(
        id=218,
        name="私家侦探",
        credit_min=9,
        credit_max=40,
        skill_points_formula="EDU*2+MAX(APP,DEX)*2",
        description="《克苏鲁煤气灯》1980s职业，使用前请征得KP同意。",
        skill_ids=[
            "accounting",
            "law",
            "library-use",
            "listen",
            "lock-smith",
            "photography",
            "spot-hidden",
        ],
        choice_slots=[
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="两项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=None,
                label="任意一项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=219,
        name="记者",
        credit_min=9,
        credit_max=30,
        skill_points_formula="EDU*2+MAX(APP,DEX)*2",
        description="《克苏鲁煤气灯》1980s职业，使用前请征得KP同意。",
        skill_ids=[
            "appraise",
            "dodge",
            "language-native",
            "library-use",
            "listen",
            "photography",
            "psychology",
            "spot-hidden",
        ],
        choice_slots=[
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="两项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "language-foreign-1",
                    "language-foreign-2",
                    "language-foreign-3",
                ],
                label="外语（任一）",
            ),
        ],
    ),
    OccupationSpec(
        id=220,
        name="劳工",
        credit_min=0,
        credit_max=10,
        skill_points_formula="EDU*2+STR*2",
        description="《克苏鲁煤气灯》1980s职业，使用前请征得KP同意。",
        skill_ids=["appraise", "dodge", "first-aid", "heavy-machinery", "mechanical-repair"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="一项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=["art-craft-1", "art-craft-2", "art-craft-3"],
                label="从以下任选两种：攀爬、斗殴、手艺（任意）、马车驾驶、驾驶：船",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=None,
                label="任意一项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=221,
        name="律师",
        credit_min=20,
        credit_max=80,
        skill_points_formula="EDU*4",
        description="《克苏鲁煤气灯》1980s职业，使用前请征得KP同意。",
        skill_ids=[
            "accounting",
            "appraise",
            "history",
            "law",
            "library-use",
            "listen",
            "psychology",
        ],
        choice_slots=[
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="两项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=None,
                label="任意两项其他个人或时代特长",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "language-foreign-1",
                    "language-foreign-2",
                    "language-foreign-3",
                ],
                label="外语（任一）",
            ),
        ],
    ),
    OccupationSpec(
        id=222,
        name="医生",
        credit_min=30,
        credit_max=70,
        skill_points_formula="EDU*4",
        description="《克苏鲁煤气灯》1980s职业，使用前请征得KP同意。",
        skill_ids=[
            "first-aid",
            "library-use",
            "medicine",
            "psychology",
            "science-biology",
            "science-pharmacy",
        ],
        choice_slots=[
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=None,
                label="任意两项其他个人或时代特长",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "language-foreign-1",
                    "language-foreign-2",
                    "language-foreign-3",
                ],
                label="外语（任一）",
            ),
        ],
    ),
    OccupationSpec(
        id=223,
        name="警察",
        credit_min=9,
        credit_max=30,
        skill_points_formula="EDU*2+MAX(STR,DEX)*2",
        description="《克苏鲁煤气灯》1980s职业，使用前请征得KP同意。",
        skill_ids=[
            "dodge",
            "fighting-brawl",
            "firearm-handgun",
            "first-aid",
            "law",
            "listen",
            "psychology",
            "spot-hidden",
            "stealth",
        ],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="一项社交技能（取悦、话术、恐吓、说服）",
            ),
        ],
    ),
    OccupationSpec(
        id=224,
        name="教授/学者",
        credit_min=20,
        credit_max=50,
        skill_points_formula="EDU*4",
        description="《克苏鲁煤气灯》1980s职业，使用前请征得KP同意。",
        skill_ids=["library-use", "psychology"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="一项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=6,
                candidate_skill_ids=None,
                label="至多六种额外的学识技巧作为个人专长",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "language-foreign-1",
                    "language-foreign-2",
                    "language-foreign-3",
                ],
                label="外语（任一）",
            ),
        ],
    ),
    OccupationSpec(
        id=225,
        name="科学家",
        credit_min=10,
        credit_max=60,
        skill_points_formula="EDU*4",
        description="《克苏鲁煤气灯》1980s职业，使用前请征得KP同意。",
        skill_ids=["history", "library-use", "mechanical-repair", "spot-hidden"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["art-craft-1", "art-craft-2", "art-craft-3"],
                label="手艺（任意）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="一项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=6,
                candidate_skill_ids=None,
                label="至多六种其他学识技巧作为个人专长",
            ),
        ],
    ),
    OccupationSpec(
        id=226,
        name="佣人",
        credit_min=0,
        credit_max=10,
        skill_points_formula="EDU*2+MAX(APP,DEX)*2",
        description="《克苏鲁煤气灯》1980s职业，使用前请征得KP同意。",
        skill_ids=["dodge", "listen", "stealth"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["art-craft-1", "art-craft-2", "art-craft-3"],
                label="手艺（任意）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=None,
                label="任意一项其他个人或时代特长",
            ),
            SkillChoiceSlot(
                count=3,
                candidate_skill_ids=[
                    "language-foreign-1",
                    "language-foreign-2",
                    "language-foreign-3",
                ],
                label="从以下中最多选取三个：会计，估价，马车驾驶，礼仪，急救，其他语言（欧洲），说服",
            ),
        ],
    ),
    OccupationSpec(
        id=227,
        name="店主",
        credit_min=9,
        credit_max=30,
        skill_points_formula="EDU*2+MAX(APP,DEX)*2",
        description="《克苏鲁煤气灯》1980s职业，使用前请征得KP同意。",
        skill_ids=["accounting", "appraise", "listen", "psychology", "spot-hidden"],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["art-craft-1", "art-craft-2", "art-craft-3"],
                label="手艺（任意）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="一项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=None,
                label="任意一项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=228,
        name="士兵",
        credit_min=9,
        credit_max=30,
        skill_points_formula="EDU*2+MAX(STR,DEX)*2",
        description="《克苏鲁煤气灯》1980s职业，使用前请征得KP同意。",
        skill_ids=[
            "dodge",
            "firearm-rifle",
            "first-aid",
            "listen",
            "mechanical-repair",
            "spot-hidden",
            "stealth",
        ],
        choice_slots=[
            SkillChoiceSlot(
                count=2,
                candidate_skill_ids=None,
                label="任意两项其他个人或时代特长",
            ),
        ],
    ),
    OccupationSpec(
        id=229,
        name="密探",
        credit_min=30,
        credit_max=70,
        skill_points_formula="EDU*2+MAX(APP,DEX)*2",
        description="《克苏鲁煤气灯》1980s职业，使用前请征得KP同意。",
        skill_ids=[
            "disguise",
            "history",
            "library-use",
            "listen",
            "lock-smith",
            "navigation",
            "psychology",
            "spot-hidden",
            "stealth",
        ],
        choice_slots=[
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=["charm", "fast-talk", "intimidate", "persuade"],
                label="一项社交技能（取悦、话术、恐吓、说服）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "fighting-brawl",
                    "fighting-sword",
                    "fighting-axe",
                    "fighting-spear",
                    "fighting-whip",
                    "fighting-chain",
                    "fighting-knife",
                ],
                label="格斗（任意）",
            ),
            SkillChoiceSlot(
                count=1,
                candidate_skill_ids=[
                    "language-foreign-1",
                    "language-foreign-2",
                    "language-foreign-3",
                ],
                label="外语（任一）",
            ),
        ],
    ),
]


def build_coc7_ruleset() -> RulesetRead:
    """组装成 `RulesetRead`，供 seed 写入 `GameSystem.ruleset` /
    `get_ruleset` 兜底使用。"""
    return RulesetRead(
        attributes=COC7_ATTRIBUTES,
        attribute_point_buy=COC7_ATTRIBUTE_POINT_BUY,
        age_range=COC7_AGE_RANGE,
        skills=COC7_SKILLS,
        occupations=COC7_OCCUPATIONS,
    )
