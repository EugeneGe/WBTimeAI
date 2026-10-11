"""``ExecutionPolicyEngine``（三类超时 / 幂等安全重试 / 退避；设计 §2.7.2）。

- 三类独立超时：``model_timeout_ms`` / ``tool_timeout_ms`` / ``run_timeout_ms``；
- **幂等安全重试**：仅对 ``429`` / ``5xx`` / ``timeout`` 重试；**不重试**入参校验失败 /
  权限拒绝 / 其它 ``4xx``；
- **退避**：exponential + jitter（上限 ``max_ms``）；
- 纯逻辑（零 SQL）；重试产生**新 ``tool_call`` 行**（``attempt`` 递增）由仓储保证（§5 #4）。
"""

from __future__ import annotations

import random
import re
from typing import Any

from astra_core import ErrorCode
from astra_domain import ExecutionPolicy
from astra_domain.constants import DEFAULT_MAX_RETRY

__all__ = ["ExecutionPolicyEngine"]

#: 从错误串中抽取 HTTP 风格状态码。
_HTTP_CODE_RE = re.compile(r"\d{3}")

#: 视为「超时」类错误的错误码（可重试）。
_TIMEOUT_CODES = {str(ErrorCode.TOOL_TIMEOUT)}

#: 永不重试的错误码（入参校验 / 权限 / 未找到 等）。
_NEVER_RETRY_CODES = {
    str(ErrorCode.VALIDATION_ERROR),
    str(ErrorCode.PERMISSION_DENIED),
    str(ErrorCode.NOT_FOUND),
    str(ErrorCode.UNAUTHORIZED),
    str(ErrorCode.CONFIGURATION_ERROR),
}


class ExecutionPolicyEngine:
    """执行策略引擎（超时 / 重试 / 退避；纯逻辑）。"""

    def __init__(self, policy: ExecutionPolicy | None = None) -> None:
        self._policy = policy or ExecutionPolicy()

    @property
    def policy(self) -> ExecutionPolicy:
        """当前执行策略。"""
        return self._policy

    @property
    def model_timeout_ms(self) -> int:
        """模型调用超时（毫秒）。"""
        return self._policy.model_timeout_ms

    @property
    def tool_timeout_ms(self) -> int:
        """工具调用超时（毫秒）。"""
        return self._policy.tool_timeout_ms

    @property
    def run_timeout_ms(self) -> int:
        """Run 级总超时（毫秒）。"""
        return self._policy.run_timeout_ms

    @property
    def max_retry(self) -> int:
        """最大重试次数。"""
        return self._policy.max_retry

    def is_retryable(self, *, error_code: str | None = None, status: str | None = None) -> bool:
        """判断一次失败是否**幂等安全可重试**（429 / 5xx / timeout）。"""
        if error_code is not None:
            if error_code in _NEVER_RETRY_CODES:
                return False
            if error_code in _TIMEOUT_CODES and "timeout" in self._policy.retry_on:
                return True
            for candidate in _http_codes(error_code):
                if self._is_retryable_code(candidate):
                    return True
        if status is not None:
            for candidate in _http_codes(str(status)):
                if self._is_retryable_code(candidate):
                    return True
            if str(status).lower() == "timeout" and "timeout" in self._policy.retry_on:
                return True
        return False

    def _is_retryable_code(self, code: str) -> bool:
        """判断 HTTP 风格状态码是否可重试（``429`` / ``5xx``）。"""
        if code == "429" and "429" in self._policy.retry_on:
            return True
        if code.startswith("5") and "5xx" in self._policy.retry_on:
            return True
        return False

    def should_retry(
        self,
        *,
        attempt: int,
        error_code: str | None = None,
        status: str | None = None,
    ) -> bool:
        """判断第 ``attempt`` 次尝试失败后是否应重试。

        Args:
            attempt: **已发生**的尝试次数（从 1 起）。
            error_code: 失败错误码（``ErrorCode`` 字面值）。
            status: HTTP / 状态字符串（如 ``"429"`` / ``"500"``）。

        Returns:
            若 ``attempt <= max_retry`` 且 :meth:`is_retryable` 为真，返回 ``True``。
        """
        if attempt > self.max_retry:
            return False
        return self.is_retryable(error_code=error_code, status=status)

    def backoff_ms(self, attempt: int, *, rng: random.Random | None = None) -> int:
        """返回第 ``attempt`` 次重试前的退避毫秒数（exponential + jitter）。"""
        backoff: dict[str, Any] = self._policy.backoff or {}
        base_ms = int(backoff.get("base_ms", 1000))
        max_ms = int(backoff.get("max_ms", 30000))
        exponent = max(0, int(attempt) - 1)
        delay = min(max_ms, base_ms * (2**exponent))
        if backoff.get("jitter", True):
            generator = rng or random
            delay = int(generator.uniform(0.5 * delay, delay)) if delay else 0
        return max(0, delay)

    @staticmethod
    def default_max_retry() -> int:
        """默认最大重试次数（常量）。"""
        return DEFAULT_MAX_RETRY


def _http_codes(text: str) -> list[str]:
    """从字符串中抽取 HTTP 风格状态码（如 ``HTTP_500`` → ``["500"]``）。"""
    return _HTTP_CODE_RE.findall(text or "")
