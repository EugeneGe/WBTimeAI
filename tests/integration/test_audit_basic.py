"""基础审计消费集成测试（W3 / T2-17；设计 §2.18；验收 ``I-P2-23`` / **DoD D11**）。

覆盖：

- ``RepositoryAuditSink`` 经**注入的**领域 ``AuditRepository`` 落 ``audit_log``，
  **四要素**（who / action / resource / outcome）齐全；
- 写库失败 → **降级本地落盘**（JSON Line）+ 告警，**不静默丢弃**；
- ``fallback_enabled=False`` 时失败仅告警（``on_error``），不落盘；
- ``health()`` 反映落点健康。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from astra_audit import RepositoryAuditSink, resolve_fallback_dir
from astra_domain import AUDIT_OUTCOME_SUCCESS, AuditLog


def _record(**overrides: Any) -> AuditLog:
    """构造一条**四要素齐全**的审计记录。"""
    values: dict[str, Any] = {
        "tenant_id": "tenant-t17",
        "user_id": "user-who-1",
        "action": "auth.login",
        "resource_type": "session",
        "resource_id": "sess-1",
        "outcome": AUDIT_OUTCOME_SUCCESS,
        "request_id": "req-t17-1",
        "metadata": {"ip": "10.0.0.1"},
    }
    values.update(overrides)
    return AuditLog(**values)


class _BrokenRepository:
    """写库必失败的仓储（触发降级）。"""

    def __init__(self) -> None:
        self.attempts = 0

    def add(self, record: AuditLog) -> AuditLog:  # noqa: ARG002 - 模拟写库失败
        self.attempts += 1
        raise RuntimeError("db down")

    def exists_request_id(self, request_id: str) -> bool:  # noqa: ARG002
        return False

    def list_by_tenant(self, tenant_id: str, *, limit: int = 100) -> list[AuditLog]:  # noqa: ARG002
        return []


def test_repository_sink_persists_four_elements(session_factory: Any) -> None:
    """写库成功：``audit_log`` 落库，四要素齐全。"""
    from astra_database import SqlAuditRepository

    repository = SqlAuditRepository(session_factory)
    sink = RepositoryAuditSink(repository=repository)
    sink.write(_record())

    persisted = repository.list_by_tenant("tenant-t17")
    assert len(persisted) == 1
    row = persisted[0]
    assert row.user_id == "user-who-1"  # who
    assert row.action == "auth.login"  # action
    assert row.resource_type == "session" and row.resource_id == "sess-1"  # resource
    assert row.outcome == AUDIT_OUTCOME_SUCCESS  # outcome
    assert sink.health().ok is True


def test_write_failure_falls_back_to_local_spool(tmp_path: Path) -> None:
    """写库失败 → 降级本地落盘（**不静默丢弃**）。"""
    broken = _BrokenRepository()
    sink = RepositoryAuditSink(repository=broken, fallback_dir=tmp_path)
    sink.write(_record(request_id="req-fallback-1"))

    files = list(tmp_path.glob("audit-*.jsonl"))
    assert files, "写库失败时应降级本地落盘"
    content = files[0].read_text(encoding="utf-8")
    assert "req-fallback-1" in content
    assert "auth.login" in content
    assert broken.attempts == 1
    assert sink.failure_count == 1
    assert sink.health().ok is False


def test_fallback_disabled_alerts_without_spool(tmp_path: Path) -> None:
    """``fallback_enabled=False`` → 不落盘，但经 ``on_error`` 告警（不静默）。"""
    alerts: list[Exception] = []
    sink = RepositoryAuditSink(
        repository=_BrokenRepository(),
        fallback_dir=tmp_path,
        fallback_enabled=False,
        on_error=lambda event, exc: alerts.append(exc),
    )
    sink.write(_record(request_id="req-alert-1"))

    assert list(tmp_path.glob("audit-*.jsonl")) == []
    assert len(alerts) == 1, "降级关闭时仍须告警（不静默丢弃）"


def test_resolve_fallback_dir_prefers_explicit(tmp_path: Path) -> None:
    """显式目录优先；缺省回退用户主目录约定。"""
    assert resolve_fallback_dir(tmp_path) == tmp_path
    assert resolve_fallback_dir(None).name == "audit-spool"
