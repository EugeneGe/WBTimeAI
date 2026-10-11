"""安全层共享常量与校验工具（``astra_security``）。

集中定义**主密钥最小长度**等跨模块常量，供 :mod:`astra_security.crypto`、
:mod:`astra_security.jwt`、:mod:`astra_security.secret_provider` 复用，避免长度
口径散落各处（设计 §2.12 / §0.3 T01 级必闭合项 P0-05）。

🔴 校验失败一律抛 :class:`~astra_core.DomainError`，错误码
:attr:`~astra_core.ErrorCode.CONFIGURATION_ERROR`；**错误信息绝不含密钥明文**。
"""

from __future__ import annotations

from astra_core import DomainError, ErrorCode

__all__ = ["MIN_SECRET_KEY_BYTES", "ensure_secret_key_length"]

#: ``ASTRA_SECRET_KEY``（主密钥）最小字节长度。
#:
#: HS256 的密钥空间应至少与哈希输出等强（≥256 bit = 32 字节）；同时对齐
#: AES-256 的 32 字节密钥强度。短密钥由 :func:`ensure_secret_key_length` 拒绝
#: （``CONFIGURATION_ERROR``）。
MIN_SECRET_KEY_BYTES = 32


def ensure_secret_key_length(secret: str, *, name: str = "ASTRA_SECRET_KEY") -> str:
    """校验主密钥长度（≥ :data:`MIN_SECRET_KEY_BYTES` 字节），并原样返回。

    以 UTF-8 编码后的字节长度为准（中文字符等按实际字节数计）。

    Args:
        secret: 待校验的主密钥字符串。
        name: 用于错误信息的密钥名（默认 ``ASTRA_SECRET_KEY``）。

    Returns:
        校验通过的原字符串（便于链式使用）。

    Raises:
        DomainError: 密钥为空或短于 :data:`MIN_SECRET_KEY_BYTES` 字节时
            （``CONFIGURATION_ERROR``）。错误信息仅含**长度**，不含密钥内容。
    """
    if not secret:
        raise DomainError(
            f"{name} 不能为空",
            code=ErrorCode.CONFIGURATION_ERROR,
        )
    length = len(secret.encode("utf-8"))
    if length < MIN_SECRET_KEY_BYTES:
        raise DomainError(
            f"{name} 长度不足：需 ≥ {MIN_SECRET_KEY_BYTES} 字节，实际 {length} 字节；"
            "请设置足够强随机的主密钥。",
            code=ErrorCode.CONFIGURATION_ERROR,
        )
    return secret
