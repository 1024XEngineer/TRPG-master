"""DeepSeek OpenAI-compatible structured JSON client."""

from __future__ import annotations

import json

import httpx
from collaboration_framework.contracts import JsonObject

from app.adapters.openai_models import StructuredJsonClient
from app.adapters.qwen_models import chat_completion_output_text


class DeepSeekChatCompletionsJsonClient(StructuredJsonClient):
    """Generate a JSON candidate through DeepSeek Chat Completions JSON mode."""

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
        schema_name: str,
        schema: JsonObject,
        instructions: str,
        input_payload: JsonObject,
    ) -> JsonObject:
        schema_json = json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
        system_message = (
            f"{instructions}\n\n"
            "只返回一个 JSON 对象，不要使用 Markdown 代码围栏，也不要添加解释文字。"
            f"返回对象必须符合下面名为“{schema_name}”的 schema：\n{schema_json}"
        )
        request_payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_message},
                {
                    "role": "user",
                    "content": json.dumps(input_payload, ensure_ascii=False),
                },
            ],
            "response_format": {"type": "json_object"},
        }
        async with httpx.AsyncClient(
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            timeout=self._timeout_seconds,
            transport=self._transport,
        ) as client:
            response = await client.post(
                f"{self._base_url}/chat/completions",
                json=request_payload,
            )
            response.raise_for_status()

        output_text = chat_completion_output_text(
            response.json(),
            provider_name="DeepSeek",
        )
        parsed = json.loads(output_text)
        if not isinstance(parsed, dict):
            raise ValueError("DeepSeek structured output must be a JSON object")
        return parsed


__all__ = ["DeepSeekChatCompletionsJsonClient"]
