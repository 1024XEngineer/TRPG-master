"""将生图 provider 返回的 URL/Data URI 安全转换为可持久化头像二进制。"""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import ipaddress
import socket
import warnings
from dataclasses import dataclass
from io import BytesIO
from urllib.parse import urljoin, urlparse

import httpx
from PIL import Image, UnidentifiedImageError

from app.service.portrait_generation import (
    PortraitImageGenerationError,
    PortraitImageTimeoutError,
)

_ALLOWED_FORMATS = {
    "PNG": "image/png",
    "JPEG": "image/jpeg",
    "WEBP": "image/webp",
}
_MAX_IMAGE_DIMENSION = 4096
_MAX_REDIRECTS = 3
# Pillow 会在打开图片头时根据该值触发解压炸弹保护；之后仍会逐边检查尺寸。
Image.MAX_IMAGE_PIXELS = _MAX_IMAGE_DIMENSION * _MAX_IMAGE_DIMENSION


@dataclass(frozen=True, slots=True)
class MaterializedPortraitImage:
    """已经通过格式、尺寸和完整解码校验，可直接写入数据库的头像。"""

    content: bytes
    content_type: str
    content_hash: str


class PortraitImageMaterializer:
    """下载或解码上游图片，并在入库前完成安全边界校验。"""

    def __init__(
        self,
        *,
        max_bytes: int,
        timeout_seconds: float,
        transport: httpx.AsyncBaseTransport | None = None,
        resolve_dns: bool = True,
    ) -> None:
        self._max_bytes = max_bytes
        self._timeout_seconds = timeout_seconds
        self._transport = transport
        self._resolve_dns = resolve_dns

    async def materialize(self, image_url: str) -> MaterializedPortraitImage:
        """按地址类型取得原始字节，再用 Pillow 确认它是完整、安全的光栅图片。"""
        if image_url.startswith("data:"):
            content = self._decode_data_uri(image_url)
        else:
            content = await self._download(image_url)
        return await asyncio.to_thread(self._validate_image, content)

    def _decode_data_uri(self, value: str) -> bytes:
        header, separator, encoded = value.partition(",")
        if not separator or ";base64" not in header.lower():
            raise PortraitImageGenerationError("图片生成服务返回了无效图片")
        declared_type = header[5:].split(";", 1)[0].lower()
        if declared_type not in _ALLOWED_FORMATS.values():
            raise PortraitImageGenerationError("图片生成服务返回了不支持的图片格式")
        # Base64 文本本身也先限长，避免在真正解码前就分配远超文件上限的内存。
        if len(encoded) > ((self._max_bytes + 2) // 3) * 4 + 4:
            raise PortraitImageGenerationError("生成的图片超过大小限制")
        try:
            content = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise PortraitImageGenerationError("图片生成服务返回了无效图片") from exc
        self._check_size(content)
        return content

    async def _download(self, value: str) -> bytes:
        current_url = value
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout_seconds,
                transport=self._transport,
            ) as client:
                for redirect_count in range(_MAX_REDIRECTS + 1):
                    await self._validate_remote_url(current_url)
                    async with client.stream(
                        "GET", current_url, follow_redirects=False
                    ) as response:
                        if response.is_redirect:
                            location = response.headers.get("location")
                            if not location or redirect_count >= _MAX_REDIRECTS:
                                raise PortraitImageGenerationError("图片下载重定向无效或过多")
                            current_url = urljoin(current_url, location)
                            continue
                        response.raise_for_status()
                        chunks: list[bytes] = []
                        total = 0
                        async for chunk in response.aiter_bytes():
                            total += len(chunk)
                            if total > self._max_bytes:
                                raise PortraitImageGenerationError("生成的图片超过大小限制")
                            chunks.append(chunk)
                        content = b"".join(chunks)
                        self._check_size(content)
                        return content
        except PortraitImageGenerationError:
            raise
        except httpx.TimeoutException as exc:
            raise PortraitImageTimeoutError("图片下载超时") from exc
        except httpx.HTTPError as exc:
            raise PortraitImageGenerationError("图片下载失败") from exc
        raise PortraitImageGenerationError("图片下载失败")

    async def _validate_remote_url(self, value: str) -> None:
        parsed = urlparse(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise PortraitImageGenerationError("图片地址不安全")
        if not self._resolve_dns:
            return
        try:
            addresses = await asyncio.to_thread(
                socket.getaddrinfo,
                parsed.hostname,
                parsed.port or (443 if parsed.scheme == "https" else 80),
                type=socket.SOCK_STREAM,
            )
        except OSError as exc:
            raise PortraitImageGenerationError("图片地址无法解析") from exc
        if not addresses:
            raise PortraitImageGenerationError("图片地址无法解析")
        for address in addresses:
            ip = ipaddress.ip_address(address[4][0])
            if not ip.is_global:
                raise PortraitImageGenerationError("图片地址不安全")

    def _check_size(self, content: bytes) -> None:
        if not content:
            raise PortraitImageGenerationError("图片生成服务返回了空图片")
        if len(content) > self._max_bytes:
            raise PortraitImageGenerationError("生成的图片超过大小限制")

    def _validate_image(self, content: bytes) -> MaterializedPortraitImage:
        self._check_size(content)
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(BytesIO(content)) as image:
                    image_format = image.format
                    width, height = image.size
                    if image_format not in _ALLOWED_FORMATS:
                        raise PortraitImageGenerationError("图片格式仅支持 PNG、JPEG 或 WebP")
                    if width <= 0 or height <= 0 or max(width, height) > _MAX_IMAGE_DIMENSION:
                        raise PortraitImageGenerationError("生成的图片尺寸超过限制")
                    image.verify()
        except PortraitImageGenerationError:
            raise
        except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
            raise PortraitImageGenerationError("生成的图片尺寸超过限制") from exc
        except (OSError, UnidentifiedImageError, ValueError) as exc:
            raise PortraitImageGenerationError("图片生成服务返回了损坏的图片") from exc
        return MaterializedPortraitImage(
            content=content,
            content_type=_ALLOWED_FORMATS[image_format],
            content_hash=hashlib.sha256(content).hexdigest(),
        )
