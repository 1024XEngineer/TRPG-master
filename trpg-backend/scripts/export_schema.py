"""导出全部 REST DTO + WS 事件 payload 的 JSON Schema，供 trpg-sdk 的 codegen
脚本（`npm run codegen`）消费，生成 trpg-sdk/src/generated/dto.ts（issue #75）。

用法：

    uv run python scripts/export_schema.py

只在开发者手动跑 codegen 前、或 CI 的漂移检查里被调用——不是应用运行时的
一部分，所以放在 app/ 包之外，不会被 uvicorn 加载，也不影响生产代码路径。

产出的 JSON Schema 只是 Python 和 TS 生成脚本之间的临时交接格式，不提交进
git（issue #75 决策 3b）——真正提交的是 trpg-sdk 生成出来的 TS 类型。

一个模型对应一个 $defs 条目：用 pydantic 提供的 models_json_schema 把所有
模型合并导出成*一份*带共享 $defs 的 JSON Schema，而不是每个模型各自导出一份
独立文件——后者会导致互相引用的模型（比如 RoomPreview 引用 RoomPlayerRead）
在多份文件里重复定义，TS 生成脚本还要额外去重。
"""

import json
from pathlib import Path

from pydantic import BaseModel
from pydantic.json_schema import GenerateJsonSchema, models_json_schema

from app.dto import auth, character, common, game, module, replay, room, ws

# 需要导出的模型清单：REST 请求/响应体 + WS 事件 payload。
#
# ApiResponse[T] 不在这份清单里：它是一个泛型包装类型，JSON Schema 没有办法
# 忠实表达 TS 泛型（导出出来只会是某个具体 T 实例化后的样子），继续在
# trpg-sdk/src/types.ts 里手写（跟 TrpgSdkOptions/ApiError 归为一类 SDK 自有
# 基础设施类型），见 issue #75 决策 2 的精神——生成的是"数据形状"，不是需要
# 业务语义/语言特性去表达的东西。
_MODELS: list[type[BaseModel]] = [
    # auth（issue #58）
    auth.RegisterBody,
    auth.LoginBody,
    auth.UpdateNicknameBody,
    auth.AuthResult,
    auth.MeRead,
    # room（issue #39）
    room.RoomCreate,
    room.SelectModuleBody,
    room.JoinRoomBody,
    room.RoomCreateResult,
    room.RoomPlayerRead,
    room.ModuleRead,
    room.RoomPreview,
    room.MyRoomSummary,
    # character（issue #59 + issue #77 卡库）
    character.EquipmentItem,
    character.CharacterUpdateBody,
    character.CharacterDraftResult,
    character.CharacterRead,
    character.RollAttributesResult,
    character.CharacterTemplateCreateBody,
    character.CharacterTemplateRead,
    # 建卡计算/校验预览（issue #84 S2）
    character.CharacterPreviewRequest,
    character.SkillPointsBudgetView,
    character.SkillComputeView,
    character.ValidationIssueView,
    character.CharacterComputeResult,
    # 游戏目录 / 规则数据（issue #77 新增，issue #84 S1 加厚 ruleset 结构）
    game.GameRead,
    game.GameSystemRead,
    game.AttributeSpec,
    game.SkillSpec,
    game.OccupationSpec,
    game.RulesetRead,
    # 模组详情 / 导入（issue #77 新增）
    module.ModuleDetailRead,
    module.ModuleImportRequestBody,
    module.ModuleImportJobRead,
    # 复盘 / 回放（issue #77 新增）
    replay.RoomSummaryRead,
    replay.ReplayEventRead,
    # 通用响应信封里的错误详情（ApiResponse 本身手写，见上面的说明）
    common.ErrorDetail,
    # WebSocket 现有 6 个事件（issue #60/#75）
    ws.RoomJoinPayload,
    ws.PlayerReadyPayload,
    ws.GameStartPayload,
    ws.ActionSubmitPayload,
    ws.SessionBoundPayload,
    ws.NarrationPushPayload,
    # WebSocket 新增 14 个事件（issue #77）：C→S 3 个 + S→C 11 个
    ws.CheckRollPayload,
    ws.SanCheckRollPayload,
    ws.RoomRejoinPayload,
    ws.RoomStatePayload,
    ws.PlayerJoinedPayload,
    ws.TurnBeginPayload,
    ws.GameEndedPayload,
    ws.ViewPrivatePayload,
    ws.CheckRequestPayload,
    ws.CheckResultPayload,
    ws.SanCheckRequestPayload,
    ws.SanCheckResultPayload,
    ws.ClueGrantedPayload,
    ws.ErrorPayload,
]

_DEFAULT_OUT_PATH = Path(__file__).resolve().parent.parent / ".schema-export" / "models.schema.json"


class _NoFieldTitleGenerator(GenerateJsonSchema):
    """关掉 pydantic 默认给每个字段单独加的 title（比如把 `ready: bool`
    变成 `{"title": "Ready", "type": "boolean"}`）。

    这些字段级 title 对 JSON Schema 本身没有语义价值，但 TS 生成脚本
    （json-schema-to-typescript）会把任何带 title 的内联 schema 当成"应该
    单独生成一个具名类型"的信号，导致每个基础类型字段都被拆成一个多余的
    具名类型（比如 `Ready`/`Utterance` 这种没人会用的类型）。只关字段级
    title，模型（class）本身的 title 不受影响——TS 生成脚本靠它决定顶层
    interface 叫什么名字，必须保留。
    """

    def field_title_should_be_set(self, schema: object) -> bool:
        return False


def export_schema(out_path: Path) -> None:
    _, combined = models_json_schema(
        [(model, "validation") for model in _MODELS],
        title="TRPG-master DTO Schema",
        schema_generator=_NoFieldTitleGenerator,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(combined, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    export_schema(_DEFAULT_OUT_PATH)
    print(f"Schema exported to {_DEFAULT_OUT_PATH}")


if __name__ == "__main__":
    main()
