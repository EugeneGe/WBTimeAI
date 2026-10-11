"""审计 spool：本地落盘 + 启动 / 定时重放（设计 §2.18.2）。

降级落盘目录：``ASTRA_AUDIT_SPOOL_DIR``，默认 ``~/.astra-ai/audit-spool/``。

- :meth:`AuditSpool.write`：把审计记录序列化为 **JSON Line** 追加写入当日 spool 文件；
- :meth:`AuditSpool.replay`：把 spool 文件中的记录**幂等**（按 ``request_id`` 去重）重放入库；
  未成功重放的行保留，成功 / 已存在的行移除，全部处理后删除空文件。
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from astra_common.time import utcnow
from astra_domain import AuditLog, AuditRepository

__all__ = ["AuditSpool", "resolve_spool_dir", "SPOOL_DIR_ENV"]

#: spool 目录环境变量名。
SPOOL_DIR_ENV = "ASTRA_AUDIT_SPOOL_DIR"

#: 默认 spool 目录（相对用户主目录）。
_DEFAULT_SPOOL_RELATIVE = (".astra-ai", "audit-spool")

#: spool 文件前缀 / 后缀。
_FILE_PREFIX = "audit-"
_FILE_SUFFIX = ".jsonl"


def resolve_spool_dir(explicit: str | Path | None = None) -> Path:
    """解析 spool 目录。

    Args:
        explicit: 显式指定目录；为 ``None`` 时读取 ``ASTRA_AUDIT_SPOOL_DIR``，
            仍为空则回退 ``~/.astra-ai/audit-spool/``。

    Returns:
        解析后的绝对目录 :class:`~pathlib.Path`。
    """
    if explicit is not None:
        return Path(explicit).expanduser()
    env_value = os.environ.get(SPOOL_DIR_ENV)
    if env_value:
        return Path(env_value).expanduser()
    return Path.home().joinpath(*_DEFAULT_SPOOL_RELATIVE)


def _serialize(record: AuditLog) -> str:
    """把审计记录序列化为一行 JSON。"""
    payload: dict[str, Any] = {
        "id": record.id,
        "tenant_id": record.tenant_id,
        "organization_id": record.organization_id,
        "workspace_id": record.workspace_id,
        "user_id": record.user_id,
        "agent_id": record.agent_id,
        "run_id": record.run_id,
        "tool_call_id": record.tool_call_id,
        "action": record.action,
        "resource_type": record.resource_type,
        "resource_id": record.resource_id,
        "outcome": record.outcome,
        "duration_ms": record.duration_ms,
        "token_usage": record.token_usage,
        "cost": str(record.cost) if record.cost is not None else None,
        "request_id": record.request_id,
        "trace_id": record.trace_id,
        "ip": record.ip,
        "metadata": record.metadata,
        "extensions": record.extensions,
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }
    return json.dumps(payload, ensure_ascii=False, default=str)


def _deserialize(line: str) -> AuditLog:
    """把一行 JSON 反序列化为审计记录实体。"""
    data: dict[str, Any] = json.loads(line)
    cost_raw = data.get("cost")
    cost: Decimal | None = None
    if cost_raw is not None:
        try:
            cost = Decimal(str(cost_raw))
        except (InvalidOperation, ValueError):
            cost = None
    created_at: datetime | None = None
    created_raw = data.get("created_at")
    if created_raw:
        created_at = datetime.fromisoformat(str(created_raw))
    record = AuditLog(
        tenant_id=str(data.get("tenant_id", "")),
        organization_id=data.get("organization_id"),
        workspace_id=data.get("workspace_id"),
        user_id=data.get("user_id"),
        agent_id=data.get("agent_id"),
        run_id=data.get("run_id"),
        tool_call_id=data.get("tool_call_id"),
        action=str(data.get("action", "")),
        resource_type=data.get("resource_type"),
        resource_id=data.get("resource_id"),
        outcome=str(data.get("outcome", "SUCCESS")),
        duration_ms=data.get("duration_ms"),
        token_usage=dict(data.get("token_usage") or {}),
        cost=cost,
        request_id=str(data.get("request_id", "")),
        trace_id=data.get("trace_id"),
        ip=data.get("ip"),
        metadata=dict(data.get("metadata") or {}),
        extensions=dict(data.get("extensions") or {}),
    )
    if data.get("id"):
        record.id = str(data["id"])
    if created_at is not None:
        record.created_at = created_at
    return record


class AuditSpool:
    """审计落盘缓冲区（JSON Line 文件）。"""

    def __init__(self, spool_dir: str | Path | None = None) -> None:
        self._dir = resolve_spool_dir(spool_dir)

    @property
    def directory(self) -> Path:
        """返回 spool 目录。"""
        return self._dir

    def _ensure_dir(self) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)

    def _file_for_today(self, *, now: datetime | None = None) -> Path:
        stamp = (now or utcnow()).strftime("%Y%m%d")
        return self._dir / f"{_FILE_PREFIX}{stamp}{_FILE_SUFFIX}"

    def write(self, record: AuditLog) -> Path:
        """把审计记录追加写入当日 spool 文件，返回文件路径。

        Raises:
            OSError: 目录 / 文件不可写（交由上层提升为 ERROR 日志 + 计数）。
        """
        self._ensure_dir()
        path = self._file_for_today()
        with path.open("a", encoding="utf-8") as handle:
            handle.write(_serialize(record))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        return path

    def pending_files(self) -> list[Path]:
        """返回待重放的 spool 文件（按文件名升序）。"""
        if not self._dir.exists():
            return []
        return sorted(
            path for path in self._dir.glob(f"{_FILE_PREFIX}*{_FILE_SUFFIX}") if path.is_file()
        )

    def read_file(self, path: Path) -> list[AuditLog]:
        """读取单个 spool 文件的全部记录（跳过损坏行）。"""
        records: list[AuditLog] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                records.append(_deserialize(line))
            except (json.JSONDecodeError, KeyError, ValueError):
                continue
        return records

    def replay(self, repository: AuditRepository) -> int:
        """把 spool 文件中的记录重放入库（按 ``request_id`` 幂等去重）。

        Args:
            repository: 目标审计仓储（实现 :class:`AuditRepository`）。

        Returns:
            **新入库**的记录条数（已存在 / 被去重的记录不计入）。
        """
        persisted = 0
        for path in self.pending_files():
            remaining: list[str] = []
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    record = _deserialize(line)
                except (json.JSONDecodeError, KeyError, ValueError):
                    continue
                try:
                    if record.request_id and repository.exists_request_id(record.request_id):
                        continue  # 幂等去重：已入库则丢弃 spool 行
                    repository.add(record)
                    persisted += 1
                except Exception:  # noqa: BLE001 - 单行失败保留，供下次重放
                    remaining.append(line)
            if remaining:
                path.write_text("\n".join(remaining) + "\n", encoding="utf-8")
            else:
                path.unlink(missing_ok=True)
        return persisted
