"""Validate one player-visible narration over committed ActionPlan evidence."""

from __future__ import annotations

import re

from collaboration_framework.contracts import ContractError
from collaboration_framework.host.ports.action_plan import ActionPlanNarrationModelPort
from collaboration_framework.host.schemas.action_plan import (
    ActionPlanNarrationContext,
    ActionPlanNarrationOutput,
)

from .narration_policy import (
    narration_atmosphere_rejection_reason,
    narration_subject_rejection_reason,
    narration_text_rejection_reason,
    normalize_narration_text,
)
from .persistent_results import (
    sentence_span_at,
    unsupported_inventory_acquisition_claim,
    unsupported_persistent_claim,
)


class ActionPlanNarrationValidationError(ContractError):
    """一次玩家可见输出校验失败。

    ``output`` 与 ``offending_spans`` 只在拒绝可以定位到具体句子时给出，供调用方
    做句级降级——剔除违规小句后复校验剩余正文，而不是把整段替换成状态播报。
    两者都是可选的：调用方仍可只带 ``reason`` 构造。
    """

    def __init__(
        self,
        reason: str,
        *,
        output: ActionPlanNarrationOutput | None = None,
        offending_spans: tuple[tuple[int, int], ...] = (),
        schema_error_fields: tuple[str, ...] = (),
        disclosure_term_index: int | None = None,
    ) -> None:
        super().__init__("ActionPlanNarrationOutput 未通过玩家可见输出安全校验")
        self.reason = reason
        self.output = output
        self.offending_spans = offending_spans
        # 只有字段路径，不含模型正文或被拒的值——outer_schema 此前只记类别，
        # 无法判断是哪个字段的形状出了问题。
        self.schema_error_fields = schema_error_fields
        # 命中禁词的**下标**，不是词本身。禁词取自尚未公开的剧情内容，落盘等于把
        # 秘密写进日志；调用方持有与索引同序的来源表，据此还原成 id 再记录。
        self.disclosure_term_index = disclosure_term_index


_CORPSE_SEARCH_QUESTION = re.compile(
    r"(?:从哪里|哪里).{0,12}(?:找|搜)|(?:寻找|搜寻).{0,12}(?:尸体|遗体)"
)

# 只要本回合已经要单独发 NPC 回复，守秘人正文里就别再塞 NPC 的直接引语了；
# 否则前端还是会像一整段守秘人口吻那样显示，分气泡就失去意义。
_EMBEDDED_DIALOGUE_RE = re.compile(r"[“”「」『』‘’\"']")
# 配对区间：句级剔除必须整段拿掉引语，不能只掐头去尾。
_QUOTED_SPAN_RE = re.compile(r"[“「『‘\"'][^”」』’\"']*[”」』’\"']")


class ActionPlanNarrator:
    def __init__(self, model: ActionPlanNarrationModelPort) -> None:
        self._model = model

    async def narrate(
        self,
        context: ActionPlanNarrationContext,
    ) -> ActionPlanNarrationOutput:
        return self.validate(context, await self._model.generate(context))

    def validate(
        self,
        context: ActionPlanNarrationContext,
        raw: object,
    ) -> ActionPlanNarrationOutput:
        """Run every player-visible safety gate over one narration candidate.

        与 ``narrate`` 分开是为了让句级降级阶梯能在不再调用模型的情况下复校验
        剔除违规小句后的正文。
        """

        if isinstance(raw, dict) and isinstance(raw.get("text"), str):
            raw = {**raw, "text": normalize_narration_text(raw["text"])}
        try:
            output = ActionPlanNarrationOutput.model_validate(raw)
        except (TypeError, ValueError) as exc:
            raise ActionPlanNarrationValidationError(
                "outer_schema",
                schema_error_fields=_schema_error_fields(exc),
            ) from exc
        if not set(output.claimed_evidence_refs).issubset(
            context.allowed_evidence_refs
        ):
            raise ActionPlanNarrationValidationError("evidence_scope")
        committed_results = tuple(
            result
            for step in context.completed_steps
            for result in step.committed_results
        )
        # 申报字段的校验退化为对引擎真值的集合包含判断，不含任何词表。这不是
        # “信任模型”：撒谎的成本从绕过一个动词表，变成必须写一个引擎当场查表
        # 否掉的 id。
        inventory_ids = {item.id for item in context.player_view.inventory}
        if not set(output.claimed_inventory_ids).issubset(inventory_ids):
            raise ActionPlanNarrationValidationError("inventory_claim_scope")
        authoritative_states = {
            (result.target_id, result.state_key, result.state_value)
            for result in committed_results
            if result.state_key is not None
        } | {
            (entity.id, state.key, state.value)
            for entity in context.player_view.scene.visible_entities
            for state in entity.observable_state
        }
        if not {
            (claim.entity_id, claim.key, claim.value)
            for claim in output.claimed_state_changes
        }.issubset(authoritative_states):
            raise ActionPlanNarrationValidationError("state_claim_scope")
        # 先检查整段文本再判断语气；“可能/或许/据说”同样会把答案送到玩家端。
        # 禁止词索引由服务端构造且不会进入模型 payload。
        for index, term in enumerate(context.forbidden_disclosure_terms):
            if term and term.casefold() in output.text.casefold():
                raise ActionPlanNarrationValidationError(
                    "hidden_disclosure",
                    output=output,
                    offending_spans=_term_sentence_spans(output.text, term),
                    disclosure_term_index=index,
                )
        required = tuple(
            item for item in context.narration_evidence if item.required_in_narration
        )
        mentioned_required = tuple(
            item
            for item in required
            if any(
                label and label in output.text
                for label in (item.subject_name, *item.subject_aliases)
            )
        )
        if len(mentioned_required) != len(required):
            raise ActionPlanNarrationValidationError("required_evidence_missing")
        # The prose is the player-facing source of truth. Once it demonstrably
        # reports a required safe result, record its public ref deterministically
        # instead of discarding otherwise valid narration because the model
        # omitted a bookkeeping field.
        claimed = tuple(
            dict.fromkeys(
                (*output.claimed_evidence_refs, *(item.ref for item in mentioned_required))
            )
        )
        if claimed != output.claimed_evidence_refs:
            output = output.model_copy(update={"claimed_evidence_refs": claimed})
        rejection = narration_text_rejection_reason(output.text)
        if rejection is not None:
            raise ActionPlanNarrationValidationError(rejection)
        if output.npc_replies and _EMBEDDED_DIALOGUE_RE.search(output.text):
            raise ActionPlanNarrationValidationError(
                "npc_dialogue_embedded_in_text",
                output=output,
                offending_spans=_quoted_sentence_spans(output.text),
            )
        subject_rejection = narration_subject_rejection_reason(
            output.text,
            addressing_mode=getattr(context, "addressing_mode", "second_person"),
        )
        if subject_rejection is not None:
            raise ActionPlanNarrationValidationError(subject_rejection)
        atmosphere_rejection = narration_atmosphere_rejection_reason(
            output.text,
            getattr(context, "previous_published_narration", None),
        )
        if atmosphere_rejection is not None:
            raise ActionPlanNarrationValidationError(atmosphere_rejection)
        persistent_rejection = unsupported_persistent_claim(
            output.text,
            committed_results,
            context.player_view,
        )
        if persistent_rejection is not None:
            raise ActionPlanNarrationValidationError(
                f"persistent_claim_without_evidence:{persistent_rejection.reason}",
                output=output,
                offending_spans=(
                    (persistent_rejection.start, persistent_rejection.end),
                ),
            )
        inventory_rejection = unsupported_inventory_acquisition_claim(
            output.text,
            committed_results,
            context.player_view,
        )
        if inventory_rejection is not None:
            raise ActionPlanNarrationValidationError(
                f"persistent_claim_without_evidence:{inventory_rejection.reason}",
                output=output,
                offending_spans=((inventory_rejection.start, inventory_rejection.end),),
            )
        visible_dead = tuple(
            entity
            for entity in context.player_view.scene.visible_entities
            if any(
                state.key == "consciousness" and state.value == "dead"
                for state in entity.observable_state
            )
        )
        if (
            visible_dead
            and any(word in context.player_input.utterance for word in ("尸体", "遗体"))
            and _CORPSE_SEARCH_QUESTION.search(output.text)
        ):
            # PlayerView 已确认尸体就在当前场景时，不能反问玩家去哪里寻找；
            # 这会把权威可见状态重新降级成模型猜测。
            raise ActionPlanNarrationValidationError("visible_corpse_search_conflict")
        if (
            context.termination_status == "needs_clarification"
            and output.kind != "clarification"
        ):
            raise ActionPlanNarrationValidationError("clarification_kind")
        return output


def _schema_error_fields(exc: Exception) -> tuple[str, ...]:
    """Extract only the failing field paths from a schema rejection.

    ``ValidationError.errors()`` 里还带着 ``input`` 与 ``msg``，那可能包含模型
    正文；这里只取 ``loc``，与 action_plan_narration_rejected 的脱敏口径一致。
    """

    errors = getattr(exc, "errors", None)
    if not callable(errors):
        return ()
    try:
        entries = errors()
    except Exception:  # pragma: no cover - defensive; errors() 不该抛
        return ()
    paths: list[str] = []
    for entry in entries:
        location = entry.get("loc") if isinstance(entry, dict) else None
        if not location:
            continue
        path = ".".join(str(part) for part in location)
        if path not in paths:
            paths.append(path)
    return tuple(paths)


# 引语后面紧跟的这些标点要一起剔掉，否则剩下的正文会以“，”开头。
_TRAILING_CLAUSE_MARKS = "，,、；;：: \t"
# 引语前紧挨着冒号，说明前面那截是引出语而不是叙事本身。
_ATTRIBUTION_TAIL = re.compile(r"[：:]\s*$")


def _quoted_sentence_spans(text: str) -> tuple[tuple[int, int], ...]:
    """Locate the quoted-speech regions to excise, for sentence-level repair.

    引语前紧挨着冒号时左边界取到整句开头，把“他说：”这类引出语一并带走；没有冒号
    则只摘掉引语本身，句子的其余部分留着。右边界只到引语结束（再吃掉紧随的小句
    标点），不扩到句末——否则 ``他说：“我不去。”窗外传来蛙鸣。`` 会把闭引号后面那
    半句正常叙事一起连坐。

    必须按**配对**区间取，不能只取「含引号字符的句子」：一段
    ``“我是詹姆斯。你们别担心。”`` 内部就有句号，按句切分后中间那句不含任何引号，
    只剔首尾会把它原样留下——引号没了，NPC 的台词就被悄悄改写成守秘人正文，比整段
    落兜底更糟。落单的引号字符没有可靠的配对信息，仍按它自己所在的整句处理。
    """

    spans: list[tuple[int, int]] = []
    covered: set[int] = set()
    for quoted in _QUOTED_SPAN_RE.finditer(text):
        covered.update(range(quoted.start(), quoted.end()))
        start = quoted.start()
        if _ATTRIBUTION_TAIL.search(text[: quoted.start()]):
            # “他说：”这类引出语得跟着台词一起走，否则会留下半截的“他说：”。
            # 没有冒号时引语多半嵌在正常句子里（柜台上写着“蛙蛙度假村”几个字），
            # 这时只摘掉引语本身，句子的其余部分仍是合法叙事。
            start = sentence_span_at(text, quoted.start())[0]
        end = quoted.end()
        while end < len(text) and text[end] in _TRAILING_CLAUSE_MARKS:
            end += 1
        if (start, end) not in spans:
            spans.append((start, end))
    for match in _EMBEDDED_DIALOGUE_RE.finditer(text):
        if match.start() in covered:
            continue
        span = sentence_span_at(text, match.start())
        if span not in spans:
            spans.append(span)
    return tuple(sorted(spans))


def _term_sentence_spans(text: str, term: str) -> tuple[tuple[int, int], ...]:
    """Locate the sentences that leaked a forbidden term, for sentence-level repair."""

    folded_text = text.casefold()
    folded_term = term.casefold()
    if len(folded_text) != len(text):
        # casefold 可能改变长度（如 ß→ss），下标就对不上了。宁可放弃句级定位，
        # 让调用方走原有的整段兜底，也不能剔错句子。
        return ()
    spans: list[tuple[int, int]] = []
    start = folded_text.find(folded_term)
    while start != -1:
        span = sentence_span_at(text, start)
        if span not in spans:
            spans.append(span)
        start = folded_text.find(folded_term, start + 1)
    return tuple(spans)
