"""Stable application errors shared by the active Host turn pipeline."""

from __future__ import annotations


class TurnExecutionError(RuntimeError):
    """Player-safe failure raised before or during authoritative turn execution."""

    def __init__(
        self,
        code: str,
        public_message: str,
        *,
        retryable: bool,
    ) -> None:
        super().__init__(public_message)
        self.code = code
        self.public_message = public_message
        self.retryable = retryable
