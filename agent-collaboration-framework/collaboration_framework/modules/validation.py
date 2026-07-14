"""Module import and contract-quality publication boundary."""

from __future__ import annotations

from typing import Any

from ..contracts import ModuleContent

# TODO(module-publication): 将来源文档解析为 ModuleContent，补充来源引用、秘密隔离、可达性审查、
# 人工批准与版本发布。只有通过 Pydantic 和确定性语义校验的版本才能交给 AtomicActionEngine；
# 本模块不参与 LangGraph 回合状态，也不直接写游戏 EventLog。


def validate_module(payload: ModuleContent | dict[str, Any]) -> ModuleContent:
    """Validate a Python payload at the module-publication boundary."""

    return ModuleContent.model_validate(payload)


def validate_module_json(payload: str | bytes) -> ModuleContent:
    """Validate a JSON example or imported module draft."""

    return ModuleContent.model_validate_json(payload)
