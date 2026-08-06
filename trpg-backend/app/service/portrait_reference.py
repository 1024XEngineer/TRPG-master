"""加载角色肖像工作流使用的项目内置风格参考图。"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class PortraitReferenceImage:
    """Provider 使用的内存图片，不包含任何玩家人物卡数据。"""

    content: bytes
    mime_type: str
    filename: str

    @property
    def data_uri(self) -> str:
        """将内置图片转换成不会暴露文件路径的 Data URI，供上游请求使用。"""
        encoded = base64.b64encode(self.content).decode("ascii")
        return f"data:{self.mime_type};base64,{encoded}"


def load_portrait_reference_image(path_value: str | None) -> PortraitReferenceImage | None:
    """读取并校验项目参考图；配置为空、文件缺失或格式不支持时返回 None。"""
    if path_value is None or not path_value.strip():
        return None

    path = Path(path_value)
    if not path.is_absolute():
        path = Path.cwd() / path
    try:
        content = path.read_bytes()
    except OSError:
        return None

    mime_type = _detect_mime_type(content)
    if mime_type is None or not content:
        return None
    return PortraitReferenceImage(content=content, mime_type=mime_type, filename=path.name)


def _detect_mime_type(content: bytes) -> str | None:
    """仅允许常见的无损/网页图片格式，避免把任意文件发送给图片模型。"""
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    return None
