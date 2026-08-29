"""Qwen-compatible structured JSON client.

Alibaba Cloud Model Studio exposes an OpenAI-compatible API, but its
Responses endpoint does not currently document OpenAI's strict
``text.format=json_schema`` parameter. Qwen's Chat Completions endpoint does
support JSON mode, so this adapter embeds the authoritative JSON Schema in the
system message, requests a JSON object, and leaves deterministic schema
validation to the existing Pydantic application boundary.
"""

from __future__ import annotations

import json
import time

import httpx
from collaboration_framework.contracts import JsonObject

from app.adapters.openai_models import (
    StructuredJsonClient,
    _log_structured_usage,
    _safe_correlation_id,
)
from app.adapters.structured_http import (
    ModelCallTrace,
    ModelClientRetryPolicy,
    StructuredOutputError,
    decode_structured_json,
    log_structured_output_failure,
    model_http_timeout,
    post_structured_json,
    read_structured_payload,
)


class QwenChatCompletionsJsonClient(StructuredJsonClient):
    """Generate a JSON candidate through Qwen's OpenAI-compatible JSON mode."""

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
            "Return exactly one JSON object. Do not use Markdown fences or add "
            "explanatory text. The JSON object must match the following schema "
            f'named "{schema_name}":\n{schema_json}'
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
            # JSON mode is most reliable when Qwen emits only the final answer.
            "enable_thinking": False,
        }
        started_at = time.monotonic()
        trace = ModelCallTrace(
            correlation_id=_safe_correlation_id(input_payload),
            stage=schema_name,
            provider="qwen",
            model=self._model,
        )
        async with httpx.AsyncClient(
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            timeout=model_http_timeout(self._timeout_seconds),
            transport=self._transport,
        ) as client:
            transport_result = await post_structured_json(
                client,
                f"{self._base_url}/chat/completions",
                json=request_payload,
                provider="qwen",
                retry_policy=self._retry_policy,
                trace=trace,
            )

        try:
            response_payload = read_structured_payload(
                transport_result.response,
                provider_name="Qwen",
            )
            output_text = chat_completion_output_text(
                response_payload,
                provider_name="Qwen",
            )
            result = decode_structured_json(output_text, provider_name="Qwen")
        except StructuredOutputError as exc:
            log_structured_output_failure(
                trace=trace,
                duration_ms=int((time.monotonic() - started_at) * 1000),
                transport_attempts=transport_result.transport_attempts,
                error=exc,
            )
            raise
        _log_structured_usage(
            response_payload,
            provider="qwen",
            model=self._model,
            schema_name=schema_name,
            duration_ms=int((time.monotonic() - started_at) * 1000),
            correlation_id=trace.correlation_id,
            transport_attempts=transport_result.transport_attempts,
        )
        return result


def chat_completion_output_text(payload: object, *, provider_name: str) -> str:
    if not isinstance(payload, dict):
        raise StructuredOutputError(f"{provider_name} Chat Completions payload must be an object")
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise StructuredOutputError(f"{provider_name} Chat Completions payload has no choices")
    first = choices[0]
    if not isinstance(first, dict):
        raise StructuredOutputError(f"{provider_name} Chat Completions choice must be an object")
    message = first.get("message")
    if not isinstance(message, dict):
        raise StructuredOutputError(f"{provider_name} Chat Completions choice has no message")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise StructuredOutputError(f"{provider_name} Chat Completions message has no text content")
    return content


__all__ = ["QwenChatCompletionsJsonClient", "chat_completion_output_text"]
