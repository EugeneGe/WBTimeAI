"""``AuditService``——基础审计服务（设计 §2.18）。

职责：

- :meth:`AuditService.record`：字段规范化 → ``metadata`` 脱敏 → 调 ``AuditSink`` 写库；
  写库抛异常 → **降级本地落盘** + 告警日志 + 业务**不中断**；
- 落盘也失败 → 提升 ``ERROR`` 结构化日志（含 ``request_id`` / ``trace_id``）
  + ``audit_write_failure_total`` 计数；
- :meth:`AuditService.replay`：重放 spool 入库（按 ``request_id`` 幂等去重）。

硬约束（N-12）：写入失败**不得静默丢弃**；降级链「写库 → 本地落盘 → ERROR 日志」逐级兜底。

掩码（C-07）：复用 :func:`astra_security.mask_secret`（``CredentialService`` 的掩码语义），
**不复制**加密 / 掩码实现。
"""

from __future__ import annotations

import logging
import re
from typing import Any

from astra_domain import AuditLog, AuditRepository
from astra_security import mask_secret

from ..dto.audit import AuditRecordDTO
from .audit_sink import AuditSink, SqlAuditSink
from .audit_spool import AuditSpool
from .base import ApplicationService

__all__ = [
    "AuditService",
    "AUDIT_WRITE_FAILURE_TOTAL",
    "mask_sensitive_metadata",
]

#: 审计写入彻底失败计数器名（设计 §2.18.2）。
AUDIT_WRITE_FAILURE_TOTAL = "audit_write_failure_total"

#: 敏感键名标记（命中即掩码其值）。
_SENSITIVE_KEY_MARKERS: tuple[str, ...] = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "private_key",
    "access_key",
    "key",
)

#: 明文密钥模式（即便键名非敏感也掩码）。
_SECRET_VALUE_RE = re.compile(r"(sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})")


def _is_sensitive_key(key: object) -> bool:
    """判断键名是否敏感。"""
    lowered = str(key).lower()
    return any(marker in lowered for marker in _SENSITIVE_KEY_MARKERS)


def mask_sensitive_metadata(value: Any, *, _sensitive: bool = False) -> Any:
    """递归脱敏 ``metadata``（凭证 / 密钥一律掩码，**无明文**）。

    Args:
        value: 待脱敏的任意 JSON 可序列化结构。
        _sensitive: 内部标志 —— 当前节点是否处于敏感键之下。

    Returns:
        脱敏后的同构结构。
    """
    if isinstance(value, dict):
        result: dict[Any, Any] = {}
        for key, item in value.items():
            child_sensitive = _sensitive or _is_sensitive_key(key)
            result[key] = mask_sensitive_metadata(item, _sensitive=child_sensitive)
        return result
    if isinstance(value, list):
        return [mask_sensitive_metadata(item, _sensitive=_sensitive) for item in value]
    if isinstance(value, tuple):
        return tuple(mask_sensitive_metadata(item, _sensitive=_sensitive) for item in value)
    if isinstance(value, str):
        if _sensitive:
            return mask_secret(value)
        return _SECRET_VALUE_RE.sub(lambda match: mask_secret(match.group(0)), value)
    return value


class AuditService(ApplicationService):
    """基础审计应用服务（写库 + 降级落盘 + 重放）。"""

    # 依赖由 :meth:`__init__` 显式注入。
    sink: AuditSink | None
    spool: AuditSpool
    repository: AuditRepository | None
    logger: logging.Logger
    metrics: Any

    def __init__(
        self,
        *,
        repository: AuditRepository | None = None,
        sink: AuditSink | None = None,
        spool: AuditSpool | None = None,
        logger: logging.Logger | None = None,
        metrics: Any = None,
    ) -> None:
        """构造审计服务。

        Args:
            repository: 目标审计仓储（写库 / 重放）；提供 ``sink`` 时可省。
            sink: 显式写入通道（缺省时按 ``repository`` 构造 :class:`SqlAuditSink`）。
            spool: 降级落盘缓冲区（缺省按 ``ASTRA_AUDIT_SPOOL_DIR`` 解析）。
            logger: 结构化日志器（缺省取本模块 logger）。
            metrics: 可选的指标汇（需提供 ``counter(name, value=1, **tags)``）。
        """
        resolved_sink: AuditSink | None = sink
        if resolved_sink is None and repository is not None:
            resolved_sink = SqlAuditSink(repository)
        resolved_spool = spool if spool is not None else AuditSpool()
        resolved_logger = logger if logger is not None else logging.getLogger(__name__)
        super().__init__(
            sink=resolved_sink,
            spool=resolved_spool,
            repository=repository,
            logger=resolved_logger,
            metrics=metrics,
        )

    # -- 写入 ---------------------------------------------------------------

    def record(self, event: AuditRecordDTO) -> AuditLog:
        """记录一条审计事件（**不因写入失败而中断业务**）。

        Args:
            event: 审计记录 DTO（``metadata`` 将被脱敏后落库 / 落盘）。

        Returns:
            实际尝试写入的审计记录实体（``metadata`` 已脱敏）。
        """
        masked_metadata = mask_sensitive_metadata(event.metadata)
        record = event.to_entity(metadata=masked_metadata)

        if self.sink is not None:
            try:
                self.sink.write(record)
                return record
            except Exception as exc:  # noqa: BLE001 - 降级，不中断业务
                self.logger.warning(
                    "审计写库失败，降级本地落盘",
                    extra={
                        "request_id": record.request_id,
                        "trace_id": record.trace_id,
                        "action": record.action,
                        "error": str(exc),
                    },
                )
        self._spool_fallback(record)
        return record

    def _spool_fallback(self, record: AuditLog) -> None:
        """降级本地落盘；落盘亦失败 → ERROR 日志 + 计数。"""
        try:
            self.spool.write(record)
        except Exception as exc:  # noqa: BLE001 - 兜底：不静默丢弃
            self._on_total_failure(record, exc)

    def _on_total_failure(self, record: AuditLog, exc: Exception) -> None:
        """彻底失败：ERROR 结构化日志（含 request_id / trace_id）+ 计数。"""
        self.logger.error(
            "审计写入彻底失败（写库与落盘均失败）",
            extra={
                "request_id": record.request_id,
                "trace_id": record.trace_id,
                "action": record.action,
                "tenant_id": record.tenant_id,
                "error": str(exc),
            },
        )
        if self.metrics is not None:
            try:
                self.metrics.counter(AUDIT_WRITE_FAILURE_TOTAL, 1)
            except Exception:  # noqa: BLE001 - 指标失败不影响业务
                self.logger.debug("审计失败计数写入指标失败", exc_info=True)

    # -- 重放 ---------------------------------------------------------------

    def replay(self, repository: AuditRepository | None = None) -> int:
        """重放 spool 入库（按 ``request_id`` 幂等去重）。

        Args:
            repository: 目标仓储；为 ``None`` 时使用构造时的 ``repository``。

        Returns:
            新入库记录条数；无可用仓储时返回 ``0``。
        """
        target = repository if repository is not None else self.repository
        if target is None:
            return 0
        return self.spool.replay(target)
