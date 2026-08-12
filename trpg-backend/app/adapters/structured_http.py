"""Transport-level retry shared by every StructuredJsonClient implementation.

三个 provider client（OpenAI / Qwen / DeepSeek）都是「一次 POST + raise_for_status」，
超时或 5xx 会直接上抛到回合链，玩家看到的是一次无法挽回的失败。瞬态网络故障是
HTTP 客户端的固有职责，所以重试放在这一层：三个 provider 一次性受益，调用方不需要
感知 provider 差异，也不需要自己区分 4xx / 5xx / 超时。

重试耗尽后重新抛出最后一次的原始异常，上层的错误映射行为因此保持不变。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import httpx
import structlog

logger = structlog.get_logger()

# 429 是限流，不是请求本身有问题，退避后重试是正确做法；其余 4xx 重试没有意义。
_RETRYABLE_STATUS_CODES = frozenset({429})


@dataclass(frozen=True)
class ModelClientRetryPolicy:
    """有限次数的指数退避。默认值保守：一次重试、0.5 秒退避。"""

    max_attempts: int = 2
    backoff_seconds: float = 0.5

    def delay_before(self, attempt: int) -> float:
        """`attempt` 从 1 开始计数，返回第 `attempt` 次失败后的等待秒数。"""

        return self.backoff_seconds * (2 ** (attempt - 1))


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
) -> httpx.Response:
    """POST 一次结构化输出请求，瞬态失败按 `retry_policy` 重试。"""

    for attempt in range(1, retry_policy.max_attempts + 1):
        try:
            response = await client.post(url, json=json)
            response.raise_for_status()
            return response
        except Exception as exc:
            if not is_transient_model_error(exc) or attempt == retry_policy.max_attempts:
                raise
            delay = retry_policy.delay_before(attempt)
            logger.warning(
                "structured_json_request_retry",
                provider=provider,
                attempt=attempt,
                max_attempts=retry_policy.max_attempts,
                delay_seconds=delay,
                error_type=type(exc).__name__,
            )
            await asyncio.sleep(delay)
    raise AssertionError("unreachable")


__all__ = [
    "ModelClientRetryPolicy",
    "is_transient_model_error",
    "post_structured_json",
]
