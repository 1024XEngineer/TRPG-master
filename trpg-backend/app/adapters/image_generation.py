"""Image-generation providers used by the character portrait workflow."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import time
from urllib.parse import urlparse

import httpx

from app.service.portrait_generation import (
    ImageGenerationOutput,
    PortraitImageContentRejectedError,
    PortraitImageGenerationError,
    PortraitImageTimeoutError,
)


class MockImageProvider:
    async def generate(
        self, *, prompt: str, negative_prompt: str, size: str
    ) -> ImageGenerationOutput:
        digest = hashlib.sha256(f"{prompt}\n{negative_prompt}\n{size}".encode()).hexdigest()[:16]
        palettes = (
            ("#204b5e", "#d59b72"),
            ("#364f3f", "#c78f72"),
            ("#5a3f55", "#d2a17b"),
            ("#544a32", "#c99373"),
        )
        coat, skin = palettes[int(digest[:2], 16) % len(palettes)]
        svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024"
 viewBox="0 0 1024 1024">
<rect width="1024" height="1024" fill="#eee9df"/>
<rect x="64" y="64" width="896" height="20" rx="10" fill="#{digest[:6]}"/>
<circle cx="512" cy="372" r="174" fill="{skin}"/>
<path d="M188 1024c22-262 137-404 324-404s302 142 324 404H188z" fill="{coat}"/>
<path d="M378 648l134 180 134-180-48-24H426l-48 24z" fill="#f7f3eb"/>
<circle cx="451" cy="365" r="14" fill="#272520"/>
<circle cx="573" cy="365" r="14" fill="#272520"/>
<path d="M458 457c32 22 76 22 108 0" fill="none" stroke="#754b3e"
 stroke-width="12" stroke-linecap="round"/>
</svg>"""
        encoded = base64.b64encode(svg.encode()).decode()
        return ImageGenerationOutput(image_url=f"data:image/svg+xml;base64,{encoded}")


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
        self, *, prompt: str, negative_prompt: str, size: str
    ) -> ImageGenerationOutput:
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
