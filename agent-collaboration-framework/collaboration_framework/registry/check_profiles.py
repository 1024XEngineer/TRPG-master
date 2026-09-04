"""CoC7 check profiles: what a rule-owned check actually rolls.

`RuleCheckSpec.profile_id` and `RuleCheckSpec.parameters` have been in the
contract since v3 and, until this issue, had **zero consumers** outside the
contract, its tests, and a build script — one of the twelve "declared but
nobody reads it" fields catalogued during the #398 investigation.

They stayed unconsumed because nothing ever ran a rule-owned check: an active
check comes with an Agent-proposed candidate menu, and a passive one had no
path at all. Now that a passive check reaches the player, something has to
answer "roll what, against what number" without asking the Agent — that answer
is the profile.

## Scope: rolling only

A profile says which value on the sheet the d100 is compared against. It does
**not** say what the result costs. `coc7.sanity`'s `failure_loss: 1d6` is a
real parameter of a real rule, and this module deliberately does not consume
it: writing `actor.resources` is #401 的 E7 单元, and #398 §范围 excludes every
CoC rule semantic. So the profile registers those keys as *recognised* — the
rule is not malformed for declaring them — while the loss itself stays unspent.

## Why only one entry

`registry/world_actions.py` states the rule this table follows: "Adding a name
here is a claim that the Engine can execute it, so it belongs in the same
change that adds the executor, never ahead of one." `coc7.sanity` is the only
profile that any published module uses in a passive rule check (追书人 ×2、
银之锁 ×2), and it is the only one this issue can execute. `coc7.skill` appears
only on `active_action` steps, which reach the player through the Agent's
candidate menu and never through this table.

The table is owned by the CoC7 adapter. Runtime dispatch should use
`registry.rulesets` so profile ids are always resolved in a `world_ref` scope.
The compatibility helpers below remain for migration-era callers.

#483 让主动检定开始消费作者声明的技能、难度与权限，但**没有**因此登记
`coc7.skill`。它没有固定的 `resource`——目标值来自 `actor.state["skills"][skill_id]`，
不是 `ActorResources` 上某个字段——所以 `_passive_check_option` 依然执行不了它。
登记它只会让发布期校验开始放行引擎跑不动的 `passive_rule` 步，把一个发布期就能拦住
的错误推迟到运行时。主动路径的目标值走 `_validated_options`，从不经过这张表。

同理，#483 只消费决定「掷什么、怎么掷」的 `skill_id`；`success_loss` /
`failure_loss` / `habit_cap` 仍旧是 recognised-but-unspent，归 #486 / #487。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from collaboration_framework.contracts.adjudication import CheckDifficulty


@dataclass(frozen=True)
class CheckProfileRegistration:
    """Everything the Engine needs to turn a `RuleCheckSpec` into one roll."""

    # 面向玩家的名字。检定面板显示它，所以必须是玩家看得懂的词，不是 id。
    display_name: str
    # `ActorResources` 上的字段名，检定的目标值从这里读。
    resource: str
    # 检定面板上的说明。规则强制的检定没有「你打算怎么做」可言，所以这两句是
    # 固定的——它们回答的是「为什么现在要掷这个」。
    method_summary: str
    player_safe_reason: str
    default_difficulty: CheckDifficulty = "regular"
    # 本 Profile 认得、但**本期不消费**的参数键。列出来是为了把「规则写错了」
    # 和「引擎还没做到」区分开：前者该在发布期拒绝，后者不该。
    recognised_parameters: frozenset[str] = field(default_factory=frozenset)


COC7_CHECK_PROFILES: Mapping[str, CheckProfileRegistration] = MappingProxyType(
    {
        "coc7.sanity": CheckProfileRegistration(
            display_name="理智",
            resource="san",
            method_summary="眼前的景象直接冲击神智",
            player_safe_reason="规则要求此刻进行一次理智检定",
            recognised_parameters=frozenset(
                {"success_loss", "failure_loss", "habit_cap"}
            ),
        ),
    }
)

# Compatibility name for callers that inspect the built-in CoC7 catalogue.
# New runtime code must use the world-scoped adapter registry.
CHECK_PROFILES = COC7_CHECK_PROFILES


def is_registered(profile_id: str, *, world_ref: str = "coc-7e") -> bool:
    return world_ref == "coc-7e" and profile_id in COC7_CHECK_PROFILES


def registration_for(
    profile_id: str,
    *,
    world_ref: str = "coc-7e",
) -> CheckProfileRegistration | None:
    if world_ref != "coc-7e":
        return None
    return COC7_CHECK_PROFILES.get(profile_id)


__all__ = [
    "CHECK_PROFILES",
    "COC7_CHECK_PROFILES",
    "CheckProfileRegistration",
    "is_registered",
    "registration_for",
]
