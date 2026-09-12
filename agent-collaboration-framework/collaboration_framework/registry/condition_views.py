"""Safe labels and relative durations; source ids and absolute clocks stay private."""

from collaboration_framework.contracts.player_view import ActorConditionView

CONDITION_NAMES = {
    "temporary_insanity": "临时疯狂",
    "indefinite_insanity": "不定性疯狂",
    "madness_bout": "疯狂发作",
    "unconscious": "昏迷",
}
BOUT_NAMES = {
    "amnesia": "失忆",
    "robbed": "遭劫",
    "battered": "遍体鳞伤",
    "violence": "暴力",
    "ideology": "信念执着",
    "significant_person": "重要之人",
    "institutionalized": "收容",
    "flee": "逃离",
    "phobia": "恐惧",
    "mania": "狂躁",
}


def condition_views(actor, absolute_hour):
    return tuple(
        ActorConditionView(
            id=c.condition_id,
            name=CONDITION_NAMES.get(c.condition_id, c.condition_id),
            remaining_hours=max(0, c.expiry.absolute_hour - absolute_hour)
            if c.expiry and c.expiry.absolute_hour is not None
            else None,
            bout_type=BOUT_NAMES.get(c.details.get("bout_type")),
        )
        for c in actor.condition_states
        if c.status == "active"
    )
