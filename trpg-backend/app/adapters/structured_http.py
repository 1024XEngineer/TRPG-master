"""Transport-level retry shared by every StructuredJsonClient implementation.

三个 provider client（OpenAI / Qwen / DeepSeek）都是「一次 POST + raise_for_status」，
超时或 5xx 会直接上抛到回合链，玩家看到的是一次无法挽回的失败。瞬态网络故障是
HTTP 客户端的固有职责，所以重试放在这一层：三个 provider 一次性受益，调用方不需要
感知 provider 差异，也不需要自己区分 4xx / 5xx / 超时。

重试耗尽后重新抛出最后一次的原始异常，上层的错误映射行为因此保持不变。
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass

import httpx
import structlog
from collaboration_framework.contracts import JsonObject

logger = structlog.get_logger()

# 429 是限流，不是请求本身有问题，退避后重试是正确做法；其余 4xx 重试没有意义。
_RETRYABLE_STATUS_CODES = frozenset({429})


class StructuredOutputError(ValueError):
    """上游回了 200，但响应体不是一个能用的结构化结果。

    与传输故障（超时 / 连接 / 5xx）分开：那类是「没拿到回复」，这类是「拿到了
    但读不懂」——响应结构不符、正文不是合法 JSON、或者 JSON 顶层不是对象。
    两者对玩家的含义不同，错误码也不该混在一起。

    继承 `ValueError` 是为了不改变既有调用方的兜底行为。
    """


@dataclass(frozen=True)
class ModelClientRetryPolicy:
    """有限次数的指数退避。默认值保守：一次重试、0.5 秒退避。"""

    max_attempts: int = 2
    backoff_seconds: float = 0.5

    def delay_before(self, attempt: int) -> float:
        """`attempt` 从 1 开始计数，返回第 `attempt` 次失败后的等待秒数。"""

        return self.backoff_seconds * (2 ** (attempt - 1))


@dataclass(frozen=True)
class ModelCallTrace:
    """Allowlisted metadata for one structured model call.

    The trace intentionally cannot carry prompts, model output, player text, or
    Keeper payloads. Callers may omit it for non-turn model traffic.
    """

    correlation_id: str | None
    stage: str
    provider: str
    model: str


@dataclass(frozen=True)
class StructuredHttpResponse:
    response: httpx.Response
    transport_attempts: int


def is_transient_model_error(exc: BaseException) -> bool:
    """判断异常是否值得重试：超时、连接错误、5xx 与 429。"""

    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        return status >= 500 or status in _RETRYABLE_STATUS_CODES
    # TimeoutException 也是 TransportError 的子类。
    return isinstance(exc, httpx.TransportError)


async def post_structured_json(
    client: httpx.AsyncClient,
    url: str,
    *,
    json: object,
    provider: str,
    retry_policy: ModelClientRetryPolicy,
    trace: ModelCallTrace | None = None,
) -> StructuredHttpResponse:
    """POST 一次结构化输出请求，瞬态失败按 `retry_policy` 重试。"""

    started_at = time.monotonic()
    for attempt in range(1, retry_policy.max_attempts + 1):
        try:
            response = await client.post(url, json=json)
            response.raise_for_status()
            return StructuredHttpResponse(
                response=response,
                transport_attempts=attempt,
            )
        except Exception as exc:
            if not is_transient_model_error(exc) or attempt == retry_policy.max_attempts:
                logger.warning(
                    "structured_model_call_failed",
                    provider=provider,
                    action=trace.correlation_id if trace is not None else None,
                    stage=trace.stage if trace is not None else None,
                    model=trace.model if trace is not None else None,
                    duration_ms=int((time.monotonic() - started_at) * 1000),
                    transport_attempts=attempt,
                    failure_code=(
                        "transport_exhausted"
                        if is_transient_model_error(exc)
                        else "http_or_transport_rejected"
                    ),
                    error_type=type(exc).__name__,
                )
                raise
            delay = retry_policy.delay_before(attempt)
            logger.warning(
                "structured_json_request_retry",
                provider=provider,
                attempt=attempt,
                max_attempts=retry_policy.max_attempts,
                delay_seconds=delay,
                error_type=type(exc).__name__,
                action=trace.correlation_id if trace is not None else None,
                stage=trace.stage if trace is not None else None,
                model=trace.model if trace is not None else None,
            )
            await asyncio.sleep(delay)
    raise AssertionError("unreachable")


def log_structured_output_failure(
    *,
    trace: ModelCallTrace,
    duration_ms: int,
    transport_attempts: int,
    error: BaseException,
) -> None:
    """Record a safe failure after HTTP succeeds but structured decoding fails."""

    logger.warning(
        "structured_model_call_failed",
        provider=trace.provider,
        action=trace.correlation_id,
        stage=trace.stage,
        model=trace.model,
        duration_ms=max(0, duration_ms),
        transport_attempts=max(1, transport_attempts),
        failure_code="structured_output_unreadable",
        error_type=type(error).__name__,
    )


def read_structured_payload(response: httpx.Response, *, provider_name: str) -> object:
    """把 HTTP 响应体读成 JSON，失败一律抛 `StructuredOutputError`。

    解码是两层的：先 HTTP 响应体 → JSON，再模型正文 → JSON 对象。只包住第二层
    是不够的——代理或网关返回 200 加一张 HTML 错误页时，坏在第一层，同样属于
    「拿到了回复但读不懂」，不该掉进未分类兜底。
    """

    try:
        return response.json()
    except ValueError as exc:
        raise StructuredOutputError(f"{provider_name} response body is not valid JSON") from exc


def decode_structured_json(output_text: str, *, provider_name: str) -> JsonObject:
    """把模型正文解成一个 JSON 对象，失败一律抛 `StructuredOutputError`。"""

    try:
        parsed = json.loads(output_text)
    except json.JSONDecodeError as exc:
        raise StructuredOutputError(f"{provider_name} structured output is not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise StructuredOutputError(f"{provider_name} structured output must be a JSON object")
    return parsed


__all__ = [
    "ModelClientRetryPolicy",
    "ModelCallTrace",
    "StructuredHttpResponse",
    "StructuredOutputError",
    "decode_structured_json",
    "is_transient_model_error",
    "log_structured_output_failure",
    "post_structured_json",
    "read_structured_payload",
]
