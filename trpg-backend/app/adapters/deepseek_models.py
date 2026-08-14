"""DeepSeek OpenAI-compatible structured JSON client."""

from __future__ import annotations

import json

import httpx
from collaboration_framework.contracts import JsonObject

from app.adapters.openai_models import StructuredJsonClient, _log_structured_usage
from app.adapters.qwen_models import chat_completion_output_text
from app.adapters.structured_http import (
    ModelClientRetryPolicy,
    decode_structured_json,
    post_structured_json,
    read_structured_payload,
)


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
        retry_policy: ModelClientRetryPolicy | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._transport = transport
        self._retry_policy = retry_policy or ModelClientRetryPolicy()

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
            # DeepSeek 的 `thinking` 默认是 enabled（`reasoning_effort` 默认
            # high），不显式关掉，每次结构化输出前都会先产出一段推理内容——而
            # 这个 client 只要一个符合 schema 的 JSON 对象，推理过程既不读也不
            # 存，纯属白烧 token 和延迟。
            #
            # 实测（issue #330）同一个 trivial 请求，preview 用的 qnaigc 端点上
            # `deepseek/deepseek-v4-flash`：不发这个参数 151 个 completion
            # tokens（其中 145 是推理），发了之后 5 个。官方端点同样生效。
            #
            # 同目录的 Qwen client 早就用 `enable_thinking: False` 做了同一件事，
            # 只是字段名不同。
            "thinking": {"type": "disabled"},
        }
        async with httpx.AsyncClient(
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            timeout=self._timeout_seconds,
            transport=self._transport,
        ) as client:
            response = await post_structured_json(
                client,
                f"{self._base_url}/chat/completions",
                json=request_payload,
                provider="deepseek",
                retry_policy=self._retry_policy,
            )

        response_payload = read_structured_payload(response, provider_name="DeepSeek")
        _log_structured_usage(
            response_payload,
            provider="deepseek",
            model=self._model,
            schema_name=schema_name,
        )
        output_text = chat_completion_output_text(
            response_payload,
            provider_name="DeepSeek",
        )
        return decode_structured_json(output_text, provider_name="DeepSeek")


__all__ = ["DeepSeekChatCompletionsJsonClient"]
