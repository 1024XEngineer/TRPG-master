"""STTAdapter / ImageGenAdapter —— 对应 master §二/§5.2.3/ADR-6/ADR-10。

语音服务端处理（非客户端本地转写）；图像生成对应 D5，两者都走"适配器"模式，
供应商可换，统一超时+重试+兜底（master §5.3）。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class STTAdapter(Protocol):
    async def transcribe(self, audio_chunks: bytes, fmt: str) -> str:
        ...


class StubSTTAdapter:
    async def transcribe(self, audio_chunks: bytes, fmt: str) -> str:
        raise NotImplementedError("STTAdapter.transcribe: 待接入 STT 供应商")


@runtime_checkable
class ImageGenAdapter(Protocol):
    async def generate(self, prompt: str) -> str:
        """返回值是资产引用（blob_assets.storage_key），不是裸字节。"""
        ...


class StubImageGenAdapter:
    async def generate(self, prompt: str) -> str:
        raise NotImplementedError("ImageGenAdapter.generate: 待接入图像生成供应商（D5，MS1 不做）")
