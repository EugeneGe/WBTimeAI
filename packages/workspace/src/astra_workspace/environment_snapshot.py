"""环境快照**规范化 SHA-256** 摘要（T2-58 · R2；设计 §2.8.1 / §2.15.5）。

Attempt 的 ``environment_digest`` 对**镜像摘要 / Runtime / 依赖锁文件 / 受支持配置**做
**规范化**（键排序 + 紧凑 JSON）SHA-256，保证**确定性、可追溯**；并**排除任何 Secret 值**
（敏感键名一律剔除，不参与摘要）。

🔴 **纯函数模块**：仅依赖标准库（``hashlib`` / ``json``）；**零** Web / ORM / ``astra_runtime``
   （分层 L-1 / L-3）。
🔴 **敏感键策略同源**：复用 :mod:`astra_workspace.environment` 的 ``SENSITIVE_KEY_PATTERN``
   （**不**另建第二份白名单 / 判定源；承 R-R1R5-15 精神）。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from .environment import SENSITIVE_KEY_PATTERN

if TYPE_CHECKING:  # pragma: no cover - 仅类型检查期
    from .domain import WorkspaceEnvironment

__all__ = [
    "DIGEST_LENGTH",
    "compute_environment_digest",
    "environment_digest_for",
    "is_sensitive_key",
]

#: SHA-256 十六进制摘要长度。
DIGEST_LENGTH = 64


def is_sensitive_key(key: str) -> bool:
    """判断键名是否敏感（命中同源 ``SENSITIVE_KEY_PATTERN`` → 不参与摘要）。"""
    return bool(SENSITIVE_KEY_PATTERN.search(str(key)))


def _normalize(value: Any) -> Any:
    """递归规范化：映射**按键排序** + **剔除敏感键**；序列保序；标量原样。"""
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for raw_key in sorted(value.keys(), key=str):
            name = str(raw_key)
            if is_sensitive_key(name):
                continue
            normalized[name] = _normalize(value[raw_key])
        return normalized
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    # 非 JSON 原生类型 → 稳定字符串化（保证可序列化且确定性）。
    return str(value)


def compute_environment_digest(
    *,
    image_digest: str | None = None,
    runtime: Mapping[str, Any] | None = None,
    dependency_locks: Mapping[str, Any] | None = None,
    config: Mapping[str, Any] | None = None,
) -> str:
    """对镜像摘要 / Runtime / 依赖锁 / 受支持配置做**规范化** SHA-256。

    Args:
        image_digest: 镜像摘要（如 ``sha256:...``；可空）。
        runtime: 运行时描述（语言版本等；可空）。
        dependency_locks: 依赖锁文件摘要（如 ``{"poetry.lock": "<sha256>"}``；可空）。
        config: 受支持配置（非敏感；可空）。

    Returns:
        64 位十六进制 SHA-256（**不含**任何 Secret 值）。
    """
    payload = {
        "image_digest": (image_digest or "").strip(),
        "runtime": _normalize(dict(runtime or {})),
        "dependency_locks": _normalize(dict(dependency_locks or {})),
        "config": _normalize(dict(config or {})),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def environment_digest_for(environment: WorkspaceEnvironment) -> str:
    """由 :class:`~astra_workspace.domain.WorkspaceEnvironment` 计算规范化摘要。

    约定从 ``runtime`` 中识别 ``image_digest`` / ``image`` / ``dependency_locks`` / ``config``
    四个键（其余 ``runtime`` 键作为运行时描述参与摘要）；敏感键一律剔除。
    """
    runtime = dict(getattr(environment, "runtime", None) or {})
    image_digest = runtime.pop("image_digest", None) or runtime.pop("image", None)
    dependency_locks = runtime.pop("dependency_locks", None) or {}
    config = runtime.pop("config", None) or {}
    return compute_environment_digest(
        image_digest=image_digest,
        runtime=runtime,
        dependency_locks=dependency_locks,
        config=config,
    )
