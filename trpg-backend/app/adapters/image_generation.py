"""Image-generation providers used by the character portrait workflow."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import time
from io import BytesIO
from urllib.parse import urlparse

import httpx
from PIL import Image, ImageDraw

from app.service.portrait_generation import (
    ImageGenerationOutput,
    PortraitImageContentRejectedError,
    PortraitImageGenerationError,
    PortraitImageTimeoutError,
)
from app.service.portrait_reference import PortraitReferenceImage


class MockImageProvider:
    async def generate(
        self,
        *,
        prompt: str,
        negative_prompt: str,
        size: str,
        reference_image: PortraitReferenceImage | None = None,
    ) -> ImageGenerationOutput:
        digest = hashlib.sha256(f"{prompt}\n{negative_prompt}\n{size}".encode()).hexdigest()[:16]
        palettes = (
            ("#204b5e", "#d59b72"),
            ("#364f3f", "#c78f72"),
            ("#5a3f55", "#d2a17b"),
            ("#544a32", "#c99373"),
        )
        coat, skin = palettes[int(digest[:2], 16) % len(palettes)]
        # Mock 同样产出可通过真实持久化校验的 PNG，避免开发环境绕开生产安全边界。
        image = Image.new("RGB", (1024, 1024), "#eee9df")
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((64, 64, 960, 84), radius=10, fill=f"#{digest[:6]}")
        draw.ellipse((338, 198, 686, 546), fill=skin)
        draw.polygon(((188, 1024), (836, 1024), (720, 700), (512, 620), (304, 700)), fill=coat)
        draw.polygon(((378, 648), (512, 828), (646, 648), (598, 624), (426, 624)), fill="#f7f3eb")
        draw.ellipse((437, 351, 465, 379), fill="#272520")
        draw.ellipse((559, 351, 587, 379), fill="#272520")
        buffer = BytesIO()
        image.save(buffer, format="PNG", optimize=True)
        encoded = base64.b64encode(buffer.getvalue()).decode()
        return ImageGenerationOutput(image_url=f"data:image/png;base64,{encoded}")


class DashScopeImageProvider:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float,
        poll_interval_seconds: float = 2.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._poll_interval_seconds = poll_interval_seconds
        self._transport = transport

    async def generate(
        self,
        *,
        prompt: str,
        negative_prompt: str,
        size: str,
        reference_image: PortraitReferenceImage | None = None,
    ) -> ImageGenerationOutput:
        # DashScope 的当前文生图请求不接受参考图字段；服务层仍传入统一参数，
        # 这里明确忽略它并保留纯提示词生成，避免伪造一个未被上游支持的协议。
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "X-DashScope-Async": "enable",
        }
        payload = {
            "model": self._model,
            "input": {"prompt": prompt, "negative_prompt": negative_prompt},
            "parameters": {"size": size.replace("x", "*"), "n": 1},
        }
        deadline = time.monotonic() + self._timeout_seconds

        try:
            async with httpx.AsyncClient(
                headers=headers,
                timeout=min(self._timeout_seconds, 30.0),
                transport=self._transport,
            ) as client:
                response = await client.post(
                    f"{self._base_url}/services/aigc/text2image/image-synthesis",
                    json=payload,
                )
                response.raise_for_status()
                task_id = self._task_id(response.json())

                while True:
                    if time.monotonic() >= deadline:
                        raise PortraitImageTimeoutError("图片生成超时")
                    if self._poll_interval_seconds > 0:
                        await asyncio.sleep(self._poll_interval_seconds)
                    status_response = await client.get(f"{self._base_url}/tasks/{task_id}")
                    status_response.raise_for_status()
                    result = status_response.json()
                    status = self._task_status(result)
                    if status == "SUCCEEDED":
                        return ImageGenerationOutput(image_url=self._image_url(result))
                    if status in {"FAILED", "CANCELED", "UNKNOWN"}:
                        self._raise_task_failure(result)
        except PortraitImageGenerationError:
            raise
        except httpx.TimeoutException as exc:
            raise PortraitImageTimeoutError("图片生成超时") from exc
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            raise PortraitImageGenerationError("图片生成服务暂时不可用") from exc

    @staticmethod
    def _output(payload: object) -> dict:
        if not isinstance(payload, dict):
            raise ValueError("DashScope response has no output object")
        output = payload.get("output")
        if not isinstance(output, dict):
            raise ValueError("DashScope response has no output object")
        return output

    @classmethod
    def _task_id(cls, payload: object) -> str:
        task_id = cls._output(payload).get("task_id")
        if not isinstance(task_id, str) or not task_id:
            raise ValueError("DashScope response has no task id")
        return task_id

    @classmethod
    def _task_status(cls, payload: object) -> str:
        status = cls._output(payload).get("task_status")
        if not isinstance(status, str):
            raise ValueError("DashScope response has no task status")
        return status.upper()

    @classmethod
    def _image_url(cls, payload: object) -> str:
        results = cls._output(payload).get("results")
        if not isinstance(results, list) or not results or not isinstance(results[0], dict):
            raise ValueError("DashScope response has no image result")
        url = results[0].get("url")
        if not isinstance(url, str) or urlparse(url).scheme not in {"http", "https"}:
            raise ValueError("DashScope response has an invalid image URL")
        return url

    @classmethod
    def _raise_task_failure(cls, payload: object) -> None:
        output = cls._output(payload)
        code = str(output.get("code") or "").lower()
        message = str(output.get("message") or "").lower()
        if any(marker in f"{code} {message}" for marker in ("inspection", "content", "sensitive")):
            raise PortraitImageContentRejectedError("角色设定未通过图片生成服务审核")
        raise PortraitImageGenerationError("图片生成失败")


class SufyImageProvider:
    """调用 Sufy 的 OpenAI-compatible 同步生图接口。"""

    _CONTENT_REJECTION_MARKERS = (
        "content policy",
        "content safety",
        "moderation",
        "sensitive",
        "prohibited",
        "blocked",
        "审核",
        "敏感",
        "内容安全",
    )

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    async def generate(
        self,
        *,
        prompt: str,
        negative_prompt: str,
        size: str,
        reference_image: PortraitReferenceImage | None = None,
    ) -> ImageGenerationOutput:
        # OpenAI 生图协议没有通用的 negative_prompt 字段，因此将反向约束
        # 并入主提示词，避免不同 Sufy 模型对非标准字段的支持不一致。
        combined_prompt = f"{prompt}\n\n避免出现以下内容：{negative_prompt}"
        payload = {
            "model": self._model,
            "prompt": combined_prompt,
            "size": size,
            "n": 1,
        }
        if reference_image is not None:
            # Sufy 的 OpenAI-compatible 网关使用 images 数组接收图像输入；
            # Data URI 保证参考图不会变成公开 URL，也不会暴露容器内文件路径。
            payload["images"] = [reference_image.data_uri]
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(
                headers=headers,
                timeout=self._timeout_seconds,
                transport=self._transport,
            ) as client:
                response = await client.post(
                    f"{self._base_url}/images/generations",
                    json=payload,
                )
                if (
                    response.is_error
                    and reference_image is not None
                    and self._is_reference_unsupported(response)
                ):
                    # 仅在上游明确表示不支持图像输入时降级一次；普通失败不重试，
                    # 避免隐藏故障或让同一次玩家操作产生重复费用。
                    response = await client.post(
                        f"{self._base_url}/images/generations",
                        json={key: value for key, value in payload.items() if key != "images"},
                    )
                if response.is_error:
                    self._raise_http_failure(response)
                return ImageGenerationOutput(image_url=self._image_result(response.json()))
        except PortraitImageGenerationError:
            raise
        except httpx.TimeoutException as exc:
            raise PortraitImageTimeoutError("图片生成超时") from exc
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            raise PortraitImageGenerationError("图片生成服务暂时不可用") from exc

    @classmethod
    def _is_reference_unsupported(cls, response: httpx.Response) -> bool:
        """只识别明确的参考图能力错误，避免把鉴权或审核失败误判成可重试。"""
        try:
            payload = response.json()
        except ValueError:
            return False
        if not isinstance(payload, dict):
            return False
        error = payload.get("error")
        if isinstance(error, dict):
            text = f"{error.get('type', '')} {error.get('message', '')}"
        else:
            text = str(error or payload.get("message", ""))
        normalized = text.lower()
        return response.status_code in {400, 422} and any(
            marker in normalized
            for marker in (
                "image input",
                "reference image",
                "unsupported field",
                "not supported",
                "不支持",
                "参考图",
            )
        )

    @classmethod
    def _raise_http_failure(cls, response: httpx.Response) -> None:
        # 仅在内存中提取审核标记用于错误分类，不向日志或客户端透传上游原文。
        error_text = ""
        try:
            payload = response.json()
            if isinstance(payload, dict):
                error = payload.get("error")
                if isinstance(error, dict):
                    error_text = f"{error.get('type', '')} {error.get('message', '')}"
                elif isinstance(error, str):
                    error_text = error
        except ValueError:
            pass

        normalized = error_text.lower()
        if response.status_code in {400, 422} and any(
            marker in normalized for marker in cls._CONTENT_REJECTION_MARKERS
        ):
            raise PortraitImageContentRejectedError("角色设定未通过图片生成服务审核")
        raise PortraitImageGenerationError("图片生成服务暂时不可用")

    @staticmethod
    def _image_result(payload: object) -> str:
        # 网关可能返回临时 URL 或 Base64，统一转换为前端 <img> 可直接使用的字符串。
        if not isinstance(payload, dict):
            raise ValueError("Sufy response is not an object")
        data = payload.get("data")
        if not isinstance(data, list) or not data or not isinstance(data[0], dict):
            raise ValueError("Sufy response has no image result")

        result = data[0]
        url = result.get("url")
        if isinstance(url, str) and urlparse(url).scheme in {"http", "https"}:
            return url

        encoded = result.get("b64_json")
        if not isinstance(encoded, str) or not encoded:
            raise ValueError("Sufy response has no valid image result")
        # 在组装 data URI 前校验 Base64，避免将损坏的上游内容伪装成图片交给浏览器。
        decoded = base64.b64decode(encoded, validate=True)
        if not decoded:
            raise ValueError("Sufy response contains an empty image")
        return f"data:image/png;base64,{encoded}"
